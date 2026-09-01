"""Fine-grained access administration.

Custom roles, groups, per-subject allow/deny grants, per-object ACLs and the
per-tenant confidentiality policy. Everything is tenant-scoped and gated by
``access.manage``; ``/me`` is readable by any workspace principal so the UI can
tailor itself.

The resolution logic lives in ``app.authz``; this router is CRUD + validation +
audit only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import datetime as dt

from .. import authn, authz, security
from ..auth import Principal, get_db, require, require_member
from ..crypto import decrypt_secrets, encrypt_secrets
from ..database import (ApiKey, CONFIDENTIALITY_LEVELS, GRANT_ALLOW, GRANT_DENY,
                        Group, GroupMember, PermissionGrant, PrincipalRole,
                        ResourceGrant, Role, RolePermission, SUBJECT_GROUP,
                        SUBJECT_USER, SsoConnection, TENANT_ROLES, Tenant, User,
                        utcnow)
from ..rbac import (ASSIGNABLE_PERMISSIONS, PERMISSION_DESCRIPTIONS,
                    RESOURCE_PERMISSIONS, Permission)
from ..services import audit

router = APIRouter(prefix="/api/access", tags=["access"])

_manage = require(Permission.ACCESS_MANAGE)
_SUBJECTS = {SUBJECT_USER, SUBJECT_GROUP}
_RESOURCE_TYPES = {"document", "collection"}


# ── models ────────────────────────────────────────────────────────

class RoleIn(BaseModel):
    key: str = Field(min_length=2, max_length=64)
    name: str = ""
    description: str = ""
    permissions: list[str] = []


class RolePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class MemberIn(BaseModel):
    user_id: int


class RoleAssignIn(BaseModel):
    subject_type: str
    subject_id: int
    role_id: int


class GrantIn(BaseModel):
    subject_type: str
    subject_id: int
    permission: str
    effect: str = GRANT_ALLOW
    note: str = ""


class ResourceGrantIn(BaseModel):
    subject_type: str
    subject_id: int
    resource_type: str
    resource_id: str
    permission: str


class PolicyIn(BaseModel):
    confidentiality_enforced: bool


# ── helpers ──────────────────────────────────────────────────────

def _tid(p: Principal) -> int:
    return p.tenant.id


def _check_perms(perms: list[str]) -> None:
    bad = sorted(set(perms) - ASSIGNABLE_PERMISSIONS)
    if bad:
        raise HTTPException(400, f"Not assignable: {bad}. Allowed: {sorted(ASSIGNABLE_PERMISSIONS)}")


def _check_subject(db, p: Principal, stype: str, sid: int) -> None:
    if stype not in _SUBJECTS:
        raise HTTPException(400, "subject_type must be 'user' or 'group'")
    if stype == SUBJECT_USER:
        u = db.get(User, sid)
        if not u or u.tenant_id != _tid(p):
            raise HTTPException(404, "User not in this workspace")
    else:
        g = db.get(Group, sid)
        if not g or g.tenant_id != _tid(p):
            raise HTTPException(404, "Group not in this workspace")


def _role_out(db, r: Role) -> dict:
    perms = [rp.permission for rp in db.query(RolePermission)
             .filter(RolePermission.role_id == r.id).all()]
    return {"id": r.id, "key": r.key, "name": r.name or r.key,
            "description": r.description, "permissions": sorted(perms),
            "created_at": r.created_at.isoformat() if r.created_at else None}


# ── catalog / introspection ─────────────────────────────────────

@router.get("/catalog")
def catalog(principal: Principal = Depends(_manage)) -> dict:
    return {
        "permissions": [
            {"key": p, "description": PERMISSION_DESCRIPTIONS.get(p, ""),
             "resource_grantable": p in RESOURCE_PERMISSIONS}
            for p in sorted(ASSIGNABLE_PERMISSIONS)
        ],
        "confidentiality_levels": CONFIDENTIALITY_LEVELS,
        "resource_types": sorted(_RESOURCE_TYPES),
    }


@router.get("/me")
def my_access(principal: Principal = Depends(require_member), db=Depends(get_db)) -> dict:
    subs = authz.subject_ids(db, principal.user)
    role_ids = [pr.role_id for pr in db.query(PrincipalRole)
                .filter(authz._subject_filter(PrincipalRole, subs)).all()] if subs else []
    roles = db.query(Role).filter(Role.id.in_(role_ids)).all() if role_ids else []
    groups = db.query(Group).join(GroupMember, GroupMember.group_id == Group.id) \
        .filter(GroupMember.user_id == principal.user_id).all() if principal.user_id else []
    return {
        "role": principal.role,
        "permissions": sorted(principal.perms),
        "custom_roles": [{"id": r.id, "key": r.key, "name": r.name} for r in roles],
        "groups": [{"id": g.id, "name": g.name} for g in groups],
        "clearance": principal.user.clearance if principal.user else 100,
        "confidentiality_enforced": authz.confidentiality_enforced(principal.tenant),
    }


@router.get("/effective/{user_id}")
def effective_for(user_id: int, principal: Principal = Depends(_manage), db=Depends(get_db)) -> dict:
    u = db.get(User, user_id)
    if not u or u.tenant_id != _tid(principal):
        raise HTTPException(404, "User not in this workspace")
    return {"user_id": u.id, "email": u.email, "base_role": u.role,
            "permissions": sorted(authz.effective_permissions(db, u.role, u))}


# ── roles ────────────────────────────────────────────────────────

@router.get("/roles")
def list_roles(principal: Principal = Depends(_manage), db=Depends(get_db)):
    rows = db.query(Role).filter(Role.tenant_id == _tid(principal)).order_by(Role.key).all()
    return [_role_out(db, r) for r in rows]


@router.post("/roles")
def create_role(req: RoleIn, principal: Principal = Depends(_manage), db=Depends(get_db)):
    key = req.key.strip().lower().replace(" ", "-")
    _check_perms(req.permissions)
    if db.query(Role).filter(Role.tenant_id == _tid(principal), Role.key == key).first():
        raise HTTPException(409, "A role with this key already exists")
    role = Role(tenant_id=_tid(principal), key=key, name=req.name.strip() or key,
                description=req.description.strip())
    db.add(role)
    db.flush()
    for p in sorted(set(req.permissions)):
        db.add(RolePermission(role_id=role.id, permission=p))
    db.commit()
    audit.record(db, action="access.role_created", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal),
                 detail=f"{key}: {sorted(set(req.permissions))}")
    return _role_out(db, role)


@router.patch("/roles/{role_id}")
def update_role(role_id: int, req: RolePatch, principal: Principal = Depends(_manage),
                db=Depends(get_db)):
    role = db.get(Role, role_id)
    if not role or role.tenant_id != _tid(principal):
        raise HTTPException(404, "Role not found")
    if req.name is not None:
        role.name = req.name.strip() or role.key
    if req.description is not None:
        role.description = req.description.strip()
    if req.permissions is not None:
        _check_perms(req.permissions)
        db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
        for p in sorted(set(req.permissions)):
            db.add(RolePermission(role_id=role.id, permission=p))
    db.commit()
    audit.record(db, action="access.role_updated", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal), detail=role.key)
    return _role_out(db, role)


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, principal: Principal = Depends(_manage), db=Depends(get_db)):
    role = db.get(Role, role_id)
    if not role or role.tenant_id != _tid(principal):
        raise HTTPException(404, "Role not found")
    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
    db.query(PrincipalRole).filter(PrincipalRole.role_id == role.id).delete()
    db.delete(role)
    db.commit()
    audit.record(db, action="access.role_deleted", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal), detail=role.key)
    return {"deleted": role_id}


# ── groups ───────────────────────────────────────────────────────

def _group_out(db, g: Group) -> dict:
    members = db.query(GroupMember).filter(GroupMember.group_id == g.id).all()
    uids = [m.user_id for m in members]
    emails = {u.id: u.email for u in db.query(User).filter(User.id.in_(uids))} if uids else {}
    return {"id": g.id, "name": g.name, "description": g.description,
            "members": [{"user_id": m.user_id, "email": emails.get(m.user_id)} for m in members]}


@router.get("/groups")
def list_groups(principal: Principal = Depends(_manage), db=Depends(get_db)):
    rows = db.query(Group).filter(Group.tenant_id == _tid(principal)).order_by(Group.name).all()
    return [_group_out(db, g) for g in rows]


@router.post("/groups")
def create_group(req: GroupIn, principal: Principal = Depends(_manage), db=Depends(get_db)):
    if db.query(Group).filter(Group.tenant_id == _tid(principal), Group.name == req.name.strip()).first():
        raise HTTPException(409, "A group with this name already exists")
    g = Group(tenant_id=_tid(principal), name=req.name.strip(), description=req.description.strip())
    db.add(g)
    db.commit()
    audit.record(db, action="access.group_created", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal), detail=g.name)
    return _group_out(db, g)


@router.delete("/groups/{group_id}")
def delete_group(group_id: int, principal: Principal = Depends(_manage), db=Depends(get_db)):
    g = db.get(Group, group_id)
    if not g or g.tenant_id != _tid(principal):
        raise HTTPException(404, "Group not found")
    db.query(GroupMember).filter(GroupMember.group_id == g.id).delete()
    db.query(PrincipalRole).filter(PrincipalRole.subject_type == SUBJECT_GROUP,
                                   PrincipalRole.subject_id == g.id).delete()
    db.query(PermissionGrant).filter(PermissionGrant.subject_type == SUBJECT_GROUP,
                                     PermissionGrant.subject_id == g.id).delete()
    db.query(ResourceGrant).filter(ResourceGrant.subject_type == SUBJECT_GROUP,
                                   ResourceGrant.subject_id == g.id).delete()
    db.delete(g)
    db.commit()
    audit.record(db, action="access.group_deleted", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal), detail=g.name)
    return {"deleted": group_id}


@router.post("/groups/{group_id}/members")
def add_member(group_id: int, req: MemberIn, principal: Principal = Depends(_manage),
               db=Depends(get_db)):
    g = db.get(Group, group_id)
    if not g or g.tenant_id != _tid(principal):
        raise HTTPException(404, "Group not found")
    _check_subject(db, principal, SUBJECT_USER, req.user_id)
    if not db.query(GroupMember).filter(GroupMember.group_id == group_id,
                                        GroupMember.user_id == req.user_id).first():
        db.add(GroupMember(group_id=group_id, user_id=req.user_id))
        db.commit()
    return _group_out(db, g)


@router.delete("/groups/{group_id}/members/{user_id}")
def remove_member(group_id: int, user_id: int, principal: Principal = Depends(_manage),
                  db=Depends(get_db)):
    g = db.get(Group, group_id)
    if not g or g.tenant_id != _tid(principal):
        raise HTTPException(404, "Group not found")
    db.query(GroupMember).filter(GroupMember.group_id == group_id,
                                 GroupMember.user_id == user_id).delete()
    db.commit()
    return _group_out(db, g)


# ── role assignments ────────────────────────────────────────────

@router.get("/assignments")
def list_assignments(subject_type: str, subject_id: int,
                     principal: Principal = Depends(_manage), db=Depends(get_db)):
    _check_subject(db, principal, subject_type, subject_id)
    prs = db.query(PrincipalRole).filter(
        PrincipalRole.tenant_id == _tid(principal),
        PrincipalRole.subject_type == subject_type,
        PrincipalRole.subject_id == subject_id).all()
    role_map = {r.id: r for r in db.query(Role).filter(
        Role.id.in_([pr.role_id for pr in prs]))} if prs else {}
    grants = db.query(PermissionGrant).filter(
        PermissionGrant.tenant_id == _tid(principal),
        PermissionGrant.subject_type == subject_type,
        PermissionGrant.subject_id == subject_id).all()
    return {
        "roles": [{"assignment_id": pr.id, "role_id": pr.role_id,
                   "key": role_map[pr.role_id].key if pr.role_id in role_map else "?"}
                  for pr in prs],
        "grants": [{"id": g.id, "permission": g.permission, "effect": g.effect, "note": g.note}
                   for g in grants],
    }


@router.post("/role-assignments")
def assign_role(req: RoleAssignIn, principal: Principal = Depends(_manage), db=Depends(get_db)):
    _check_subject(db, principal, req.subject_type, req.subject_id)
    role = db.get(Role, req.role_id)
    if not role or role.tenant_id != _tid(principal):
        raise HTTPException(404, "Role not found")
    exists = db.query(PrincipalRole).filter(
        PrincipalRole.subject_type == req.subject_type,
        PrincipalRole.subject_id == req.subject_id,
        PrincipalRole.role_id == req.role_id).first()
    if not exists:
        db.add(PrincipalRole(tenant_id=_tid(principal), subject_type=req.subject_type,
                             subject_id=req.subject_id, role_id=req.role_id))
        db.commit()
    audit.record(db, action="access.role_assigned", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal),
                 detail=f"{role.key} -> {req.subject_type}:{req.subject_id}")
    return {"ok": True}


@router.delete("/role-assignments/{assignment_id}")
def unassign_role(assignment_id: int, principal: Principal = Depends(_manage), db=Depends(get_db)):
    pr = db.get(PrincipalRole, assignment_id)
    if not pr or pr.tenant_id != _tid(principal):
        raise HTTPException(404, "Assignment not found")
    db.delete(pr)
    db.commit()
    return {"deleted": assignment_id}


# ── permission grants ──────────────────────────────────────────

@router.post("/grants")
def create_grant(req: GrantIn, principal: Principal = Depends(_manage), db=Depends(get_db)):
    if req.effect not in (GRANT_ALLOW, GRANT_DENY):
        raise HTTPException(400, "effect must be 'allow' or 'deny'")
    _check_perms([req.permission])
    _check_subject(db, principal, req.subject_type, req.subject_id)
    # lock-out guard: cannot deny access.manage for yourself
    if (req.effect == GRANT_DENY and req.permission == Permission.ACCESS_MANAGE
            and req.subject_type == SUBJECT_USER and req.subject_id == principal.user_id):
        raise HTTPException(400, "You cannot deny your own access.manage permission")
    row = db.query(PermissionGrant).filter(
        PermissionGrant.subject_type == req.subject_type,
        PermissionGrant.subject_id == req.subject_id,
        PermissionGrant.permission == req.permission).first()
    if row:
        row.effect, row.note = req.effect, req.note.strip()
    else:
        row = PermissionGrant(tenant_id=_tid(principal), subject_type=req.subject_type,
                              subject_id=req.subject_id, permission=req.permission,
                              effect=req.effect, note=req.note.strip())
        db.add(row)
    db.commit()
    audit.record(db, action="access.grant_set", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal),
                 detail=f"{req.effect} {req.permission} -> {req.subject_type}:{req.subject_id}")
    return {"id": row.id, "permission": row.permission, "effect": row.effect}


@router.delete("/grants/{grant_id}")
def delete_grant(grant_id: int, principal: Principal = Depends(_manage), db=Depends(get_db)):
    g = db.get(PermissionGrant, grant_id)
    if not g or g.tenant_id != _tid(principal):
        raise HTTPException(404, "Grant not found")
    db.delete(g)
    db.commit()
    return {"deleted": grant_id}


# ── resource grants ────────────────────────────────────────────

@router.get("/resource-grants")
def list_resource_grants(resource_type: str, resource_id: str,
                         principal: Principal = Depends(_manage), db=Depends(get_db)):
    rows = db.query(ResourceGrant).filter(
        ResourceGrant.tenant_id == _tid(principal),
        ResourceGrant.resource_type == resource_type,
        ResourceGrant.resource_id == str(resource_id)).all()
    uids = [r.subject_id for r in rows if r.subject_type == SUBJECT_USER]
    emails = {u.id: u.email for u in db.query(User).filter(User.id.in_(uids))} if uids else {}
    return [{"id": r.id, "subject_type": r.subject_type, "subject_id": r.subject_id,
             "subject_label": emails.get(r.subject_id) if r.subject_type == SUBJECT_USER else None,
             "permission": r.permission} for r in rows]


@router.post("/resource-grants")
def create_resource_grant(req: ResourceGrantIn, principal: Principal = Depends(_manage),
                          db=Depends(get_db)):
    if req.resource_type not in _RESOURCE_TYPES:
        raise HTTPException(400, f"resource_type must be one of {sorted(_RESOURCE_TYPES)}")
    if req.permission not in RESOURCE_PERMISSIONS:
        raise HTTPException(400, f"permission must be one of {sorted(RESOURCE_PERMISSIONS)}")
    _check_subject(db, principal, req.subject_type, req.subject_id)
    row = db.query(ResourceGrant).filter(
        ResourceGrant.subject_type == req.subject_type,
        ResourceGrant.subject_id == req.subject_id,
        ResourceGrant.resource_type == req.resource_type,
        ResourceGrant.resource_id == str(req.resource_id),
        ResourceGrant.permission == req.permission).first()
    if not row:
        row = ResourceGrant(tenant_id=_tid(principal), subject_type=req.subject_type,
                            subject_id=req.subject_id, resource_type=req.resource_type,
                            resource_id=str(req.resource_id), permission=req.permission,
                            granted_by=principal.email)
        db.add(row)
        db.commit()
    audit.record(db, action="access.resource_grant_set", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal),
                 detail=f"{req.permission} {req.resource_type}:{req.resource_id} -> "
                        f"{req.subject_type}:{req.subject_id}")
    return {"id": row.id}


@router.delete("/resource-grants/{grant_id}")
def delete_resource_grant(grant_id: int, principal: Principal = Depends(_manage),
                          db=Depends(get_db)):
    g = db.get(ResourceGrant, grant_id)
    if not g or g.tenant_id != _tid(principal):
        raise HTTPException(404, "Resource grant not found")
    db.delete(g)
    db.commit()
    return {"deleted": grant_id}


# ── confidentiality policy ─────────────────────────────────────

@router.get("/policy")
def get_policy(principal: Principal = Depends(_manage)) -> dict:
    return {"confidentiality_enforced": authz.confidentiality_enforced(principal.tenant)}


@router.put("/policy")
def set_policy(req: PolicyIn, principal: Principal = Depends(_manage), db=Depends(get_db)):
    tenant = db.get(Tenant, principal.tenant.id)
    settings = dict(tenant.settings_json or {})
    settings["confidentiality_enforced"] = bool(req.confidentiality_enforced)
    tenant.settings_json = settings
    db.merge(tenant)
    db.commit()
    audit.record(db, action="access.policy_changed", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal),
                 detail=f"confidentiality_enforced={req.confidentiality_enforced}")
    return {"confidentiality_enforced": bool(req.confidentiality_enforced)}


# ── authentication policy + entitlements ──────────────────────────

class AuthPolicyIn(BaseModel):
    mfa_required: bool | None = None
    require_verified_email: bool | None = None


@router.get("/auth-policy")
def get_auth_policy(principal: Principal = Depends(_manage)) -> dict:
    s = principal.tenant.settings_json or {}
    return {
        "mfa_required": bool(s.get("mfa_required")),
        "require_verified_email": bool(s.get("require_verified_email")),
        "entitlements": authn.tenant_entitlements(principal.tenant),
    }


@router.put("/auth-policy")
def set_auth_policy(req: AuthPolicyIn, principal: Principal = Depends(_manage), db=Depends(get_db)):
    tenant = db.get(Tenant, _tid(principal))
    st = dict(tenant.settings_json or {})
    if req.mfa_required is not None:
        st["mfa_required"] = bool(req.mfa_required)
    if req.require_verified_email is not None:
        st["require_verified_email"] = bool(req.require_verified_email)
    tenant.settings_json = st
    db.merge(tenant)
    db.commit()
    audit.record(db, action="access.auth_policy_changed", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal), detail=str(req.model_dump()))
    return get_auth_policy(principal)


# ── API keys (hashed, named, revocable) ──────────────────────────

class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expires_in_days: int | None = None


def _apikey_out(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix,
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "revoked": bool(k.revoked),
            "created_at": k.created_at.isoformat() if k.created_at else None}


@router.get("/api-keys")
def list_api_keys(principal: Principal = Depends(_manage), db=Depends(get_db)):
    rows = (db.query(ApiKey).filter(ApiKey.tenant_id == _tid(principal))
            .order_by(ApiKey.created_at.desc()).all())
    return [_apikey_out(k) for k in rows]


@router.post("/api-keys")
def create_api_key(req: ApiKeyIn, principal: Principal = Depends(_manage), db=Depends(get_db)):
    raw, prefix, key_hash = security.new_api_key_pair()
    expires = (utcnow() + dt.timedelta(days=req.expires_in_days)) if req.expires_in_days else None
    row = ApiKey(tenant_id=_tid(principal), name=req.name.strip(), prefix=prefix,
                 key_hash=key_hash, created_by=principal.email, expires_at=expires)
    db.add(row)
    db.commit()
    audit.record(db, action="access.api_key_created", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal), detail=req.name)
    return {**_apikey_out(row), "api_key": raw,
            "note": "Copy this key now — it is not shown again."}


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: int, principal: Principal = Depends(_manage), db=Depends(get_db)):
    row = db.get(ApiKey, key_id)
    if not row or row.tenant_id != _tid(principal):
        raise HTTPException(404, "API key not found")
    row.revoked = 1
    db.commit()
    audit.record(db, action="access.api_key_revoked", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal), detail=row.name)
    return {"revoked": key_id}


# ── SSO connection (the 'sso' entitlement) ──────────────────────

class SsoIn(BaseModel):
    display_name: str = "SSO"
    issuer: str = ""
    client_id: str = ""
    client_secret: str | None = None       # write-only; None = unchanged, "" = clear
    allowed_domains: list[str] = []
    default_role: str = "member"
    is_active: bool = False


def _sso_out(c: SsoConnection | None, tenant) -> dict:
    entitled = authn.entitlement_enabled(tenant, "sso")
    if not c:
        return {"configured": False, "entitled": entitled}
    return {
        "configured": True, "entitled": entitled,
        "display_name": c.display_name, "issuer": c.issuer, "client_id": c.client_id,
        "client_secret_set": bool(decrypt_secrets(c.secret_encrypted).get("client_secret")),
        "allowed_domains": c.allowed_domains or [], "default_role": c.default_role,
        "is_active": bool(c.is_active),
        "callback_url": "<origin>/api/auth/sso/callback",
    }


@router.get("/sso")
def get_sso(principal: Principal = Depends(_manage), db=Depends(get_db)):
    c = db.query(SsoConnection).filter(SsoConnection.tenant_id == _tid(principal)).first()
    return _sso_out(c, principal.tenant)


@router.put("/sso")
def put_sso(req: SsoIn, principal: Principal = Depends(_manage), db=Depends(get_db)):
    if not authn.entitlement_enabled(principal.tenant, "sso"):
        raise HTTPException(402, "Single sign-on is not included in this workspace's plan")
    if req.default_role not in TENANT_ROLES:
        raise HTTPException(400, "default_role must be 'member' or 'tenant_admin'")
    c = db.query(SsoConnection).filter(SsoConnection.tenant_id == _tid(principal)).first()
    if not c:
        c = SsoConnection(tenant_id=_tid(principal))
        db.add(c)
    c.display_name = req.display_name.strip() or "SSO"
    c.issuer = req.issuer.strip().rstrip("/")
    c.client_id = req.client_id.strip()
    c.allowed_domains = [d.strip().lower() for d in req.allowed_domains if d.strip()]
    c.default_role = req.default_role
    c.is_active = bool(req.is_active)
    if req.client_secret is not None:
        cur = decrypt_secrets(c.secret_encrypted)
        if req.client_secret == "":
            cur.pop("client_secret", None)
        else:
            cur["client_secret"] = req.client_secret
        c.secret_encrypted = encrypt_secrets(cur)
    db.commit()
    audit.record(db, action="access.sso_configured", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal),
                 detail=f"issuer={c.issuer} active={c.is_active}")
    return _sso_out(c, principal.tenant)


@router.delete("/sso")
def delete_sso(principal: Principal = Depends(_manage), db=Depends(get_db)):
    c = db.query(SsoConnection).filter(SsoConnection.tenant_id == _tid(principal)).first()
    if c:
        db.delete(c)
        db.commit()
    audit.record(db, action="access.sso_removed", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=_tid(principal))
    return {"deleted": True}
