"""Fine-grained authorization — custom roles, groups, grants, resource ACLs and
clearance — layered on top of the built-in RBAC matrix in ``app.rbac``.

Effective permissions for a user U (in their tenant):

    builtin(U.role)                              # the four code-defined roles
      ∪  permissions of every custom Role assigned to U or a Group U is in
      ∪  direct 'allow' PermissionGrants for U or its groups
      −  direct 'deny'  PermissionGrants for U or its groups        ← deny wins

Resource access (one object):

    can_on(U, perm, type, id)
      = perm ∈ effective(U)                                    # global capability
      OR a matching ResourceGrant for U or its groups           # per-object share

Clearance (ABAC, opt-in per tenant via settings_json.confidentiality_enforced):
a user only sees a document whose confidentiality level ≤ U.clearance — unless
they own it, hold ``document.write.tenant``, or have an explicit ResourceGrant.

Everything here is inert until an admin creates a role / group / grant: a user
with none resolves to exactly ``ROLE_PERMISSIONS[user.role]``.
"""
from __future__ import annotations

from sqlalchemy import or_

from .database import (CONFIDENTIALITY_LEVELS, GRANT_ALLOW, GRANT_DENY,
                       GroupMember, PermissionGrant, PrincipalRole, ResourceGrant,
                       Role, RolePermission, SUBJECT_GROUP, SUBJECT_USER, User,
                       confidentiality_level)
from .rbac import ROLE_PERMISSIONS, Permission


# ── subject resolution ─────────────────────────────────────────────

def subject_ids(db, user: User | None) -> list[tuple[str, int]]:
    """The (subject_type, subject_id) pairs that apply to this user:
    the user itself plus every group they belong to."""
    if user is None:
        return []
    subs: list[tuple[str, int]] = [(SUBJECT_USER, user.id)]
    gids = [gm.group_id for gm in
            db.query(GroupMember).filter(GroupMember.user_id == user.id).all()]
    subs.extend((SUBJECT_GROUP, gid) for gid in gids)
    return subs


def _subject_filter(model, subs: list[tuple[str, int]]):
    return or_(*[
        (model.subject_type == st) & (model.subject_id == sid) for st, sid in subs
    ])


# ── effective permission set ───────────────────────────────────────

def effective_permissions(db, role: str, user: User | None) -> frozenset[str]:
    base = set(ROLE_PERMISSIONS.get(role, frozenset()))
    subs = subject_ids(db, user)
    if not subs:                                    # service key / superadmin
        return frozenset(base)

    # custom roles
    role_ids = [pr.role_id for pr in
                db.query(PrincipalRole).filter(_subject_filter(PrincipalRole, subs)).all()]
    if role_ids:
        for rp in db.query(RolePermission).filter(RolePermission.role_id.in_(role_ids)).all():
            base.add(rp.permission)

    # direct grants — deny wins, so apply allows then remove denies
    allow, deny = set(), set()
    for g in db.query(PermissionGrant).filter(_subject_filter(PermissionGrant, subs)).all():
        (allow if g.effect == GRANT_ALLOW else deny).add(g.permission)
    base |= allow
    base -= deny
    return frozenset(base)


# ── resource-level ─────────────────────────────────────────────────

def can_on(db, principal, permission: str, resource_type: str, resource_id) -> bool:
    if principal.can(permission):
        return True
    subs = subject_ids(db, principal.user)
    if not subs:
        return False
    return db.query(ResourceGrant.id).filter(
        _subject_filter(ResourceGrant, subs),
        ResourceGrant.resource_type == resource_type,
        ResourceGrant.resource_id == str(resource_id),
        ResourceGrant.permission == permission,
    ).first() is not None


def granted_resource_ids(db, principal, resource_type: str, permission: str) -> set[str]:
    """Every resource_id of the given type the principal may `permission`,
    via a ResourceGrant on the user or its groups. Used to widen list/retrieval."""
    subs = subject_ids(db, principal.user)
    if not subs:
        return set()
    rows = db.query(ResourceGrant.resource_id).filter(
        _subject_filter(ResourceGrant, subs),
        ResourceGrant.resource_type == resource_type,
        ResourceGrant.permission == permission,
    ).all()
    return {r[0] for r in rows}


# ── clearance (ABAC) ───────────────────────────────────────────────

def confidentiality_enforced(tenant) -> bool:
    return bool((tenant.settings_json or {}).get("confidentiality_enforced")) if tenant else False


def allowed_confidentialities(user: User | None, enforced: bool) -> list[str] | None:
    """The confidentiality values this user is cleared for, or None = no limit."""
    if not enforced or user is None:
        return None
    clearance = user.clearance if user.clearance is not None else 100
    allowed = [c for c, lvl in CONFIDENTIALITY_LEVELS.items() if lvl <= clearance]
    # values outside the known map are treated as most sensitive → excluded
    return allowed


def clearance_ok(user: User | None, confidentiality: str, enforced: bool) -> bool:
    if not enforced or user is None:
        return True
    clearance = user.clearance if user.clearance is not None else 100
    return confidentiality_level(confidentiality) <= clearance


# ── query-time access descriptor ───────────────────────────────────

def retrieval_access(db, principal, scope: str) -> dict:
    """Build the dict passed to rag.retrieve / vectorstore.search: identity,
    requested scope, explicitly-shared doc ids, and the confidentiality allow-list."""
    tenant = principal.tenant
    enforced = confidentiality_enforced(tenant)
    is_admin = principal.can(Permission.DOC_WRITE_TENANT)
    return {
        "user_id": principal.user_id,
        "scope": scope,
        "granted_doc_ids": sorted(
            int(x) for x in granted_resource_ids(db, principal, "document", Permission.DOC_READ)
            if str(x).isdigit()
        ),
        "allowed_confidentialities": None if is_admin else allowed_confidentialities(principal.user, enforced),
    }
