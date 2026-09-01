"""User management.

* tenant_admin — manages users inside their own tenant only. The tenant comes
  from their verified token; any tenant identifier in the request is ignored.
* superadmin   — manages users in any tenant (tenant chosen explicitly) and
  other platform admins.
Safety rails: you cannot disable or delete yourself, demote the last admin of
a tenant, or (as tenant_admin) touch users outside your tenant.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import security
from ..auth import Principal, get_db, require_user_manager
from ..database import (ROLE_MEMBER, ROLE_SUPERADMIN, ROLE_TENANT_ADMIN,
                        RefreshToken, TENANT_ROLES, Tenant, User)
from ..services import audit

router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(default="", max_length=200)
    role: str = ROLE_MEMBER
    password: str | None = None              # omit → temp password is generated
    tenant_slug: str | None = None           # superadmin only; admins use own


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    clearance: int | None = None          # ABAC max confidentiality level; needs access.manage


def _is_super(principal: Principal) -> bool:
    return principal.role == ROLE_SUPERADMIN


def _scope_tenant(principal: Principal, db,
                  tenant_slug: str | None) -> Tenant | None:
    """Resolve which tenant this operation applies to, enforcing scope."""
    if not _is_super(principal):
        return principal.tenant               # own tenant, always (any workspace user manager)
    # superadmin: explicit tenant, or None to manage platform admins
    if tenant_slug:
        tenant = db.query(Tenant).filter(Tenant.slug == tenant_slug).first()
        if not tenant:
            raise HTTPException(404, "Workspace not found")
        return tenant
    return None


def _user_out(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "full_name": u.full_name,
        "role": u.role, "is_active": bool(u.is_active),
        "clearance": u.clearance if u.clearance is not None else 100,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _guard_target(principal: Principal, target: User) -> None:
    """A workspace user manager may only touch tenant users of their own tenant."""
    if not _is_super(principal):
        if (target.tenant_id != principal.tenant.id
                or target.role not in TENANT_ROLES):
            raise HTTPException(404, "User not found")


@router.get("")
def list_users(tenant: str | None = None,
               principal: Principal = Depends(require_user_manager),
               db=Depends(get_db)):
    scope = _scope_tenant(principal, db, tenant)
    q = db.query(User)
    if scope:
        q = q.filter(User.tenant_id == scope.id)
    elif _is_super(principal):
        q = q.filter(User.role == ROLE_SUPERADMIN)
    return [_user_out(u) for u in q.order_by(User.created_at).all()]


@router.post("")
def create_user(req: UserCreate,
                principal: Principal = Depends(require_user_manager),
                db=Depends(get_db)):
    email = req.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Enter a valid email address")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "A user with this email already exists")

    role = req.role
    scope = _scope_tenant(principal, db, req.tenant_slug)
    if not _is_super(principal):
        if role not in TENANT_ROLES:
            raise HTTPException(400, "Role must be member or tenant_admin")
    else:                                                  # superadmin
        if role == ROLE_SUPERADMIN:
            scope = None
        elif role in TENANT_ROLES:
            if not scope:
                raise HTTPException(400, "tenant_slug is required for workspace users")
        else:
            raise HTTPException(400, "Unknown role")

    password = req.password or ("Kd-" + secrets.token_urlsafe(9))
    problem = security.validate_password_policy(password, email)
    if problem:
        raise HTTPException(400, problem)

    user = User(email=email, full_name=req.full_name.strip(),
                password_hash=security.hash_password(password), role=role,
                tenant_id=scope.id if scope else None,
                force_password_change=1)
    db.add(user)
    db.commit()
    audit.record(db, action="user.created", actor_email=principal.email,
                 actor_role=principal.role,
                 tenant_id=scope.id if scope else None,
                 detail=f"{email} as {role}")
    out = _user_out(user)
    if not req.password:
        out["temporary_password"] = password   # shown once, never stored raw
    return out


@router.patch("/{user_id}")
def update_user(user_id: int, req: UserUpdate,
                principal: Principal = Depends(require_user_manager),
                db=Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    _guard_target(principal, target)

    if principal.user and target.id == principal.user.id and req.is_active is False:
        raise HTTPException(400, "You cannot disable your own account")

    if req.role and req.role != target.role:
        if not _is_super(principal) and req.role not in TENANT_ROLES:
            raise HTTPException(400, "Role must be member or tenant_admin")
        if (target.role == ROLE_TENANT_ADMIN and req.role == ROLE_MEMBER
                and target.tenant_id):
            admins = (db.query(User)
                      .filter(User.tenant_id == target.tenant_id,
                              User.role == ROLE_TENANT_ADMIN,
                              User.is_active == 1).count())
            if admins <= 1:
                raise HTTPException(400, "A workspace needs at least one admin")
        target.role = req.role

    if req.full_name is not None:
        target.full_name = req.full_name.strip()
    if req.clearance is not None:
        from ..rbac import Permission
        if not principal.can(Permission.ACCESS_MANAGE):
            raise HTTPException(403, "Setting clearance requires access.manage")
        target.clearance = max(0, int(req.clearance))
    if req.is_active is not None:
        target.is_active = 1 if req.is_active else 0
        if not req.is_active:
            db.query(RefreshToken).filter(
                RefreshToken.user_id == target.id).update({"revoked": 1})

    db.commit()
    audit.record(db, action="user.updated", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=target.tenant_id,
                 detail=f"{target.email}: role={target.role} active={target.is_active}")
    return _user_out(target)


@router.post("/{user_id}/reset-password")
def reset_password(user_id: int,
                   principal: Principal = Depends(require_user_manager),
                   db=Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    _guard_target(principal, target)

    temp = "Kd-" + secrets.token_urlsafe(9)
    target.password_hash = security.hash_password(temp)
    target.password_version += 1
    target.force_password_change = 1
    target.failed_logins = 0
    target.locked_until = None
    db.query(RefreshToken).filter(
        RefreshToken.user_id == target.id).update({"revoked": 1})
    db.commit()
    audit.record(db, action="user.password_reset", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=target.tenant_id,
                 detail=target.email)
    return {"temporary_password": temp,
            "note": "Shown once. The user must change it at next sign-in."}
