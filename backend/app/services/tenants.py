"""Tenant (organization) lifecycle helpers.

Provisioning / suspension / deletion are superadmin operations exposed by
``app.routers.admin``; the mechanics live here so the router stays thin and the
"delete everything that belongs to a workspace" list has one home.

Design notes
------------
* **Suspension is reversible and lossless** — it only flips ``Tenant.status`` and
  revokes live sessions; ``app.auth.get_principal`` then refuses the workspace.
* **Deletion is exhaustive** — every table carrying a ``tenant_id`` (plus the
  per-tenant Qdrant collections) is swept, so no orphan rows survive. Keep
  :data:`TENANT_SCOPED_MODELS` in sync when a new tenant-scoped table is added.
"""
from __future__ import annotations

from ..database import (ActivityLog, ApiKey, AuditLog, ConnectorSyncRun,
                        DataConnector, Document, Group, GroupMember,
                        ModelConnector, PermissionGrant, PrincipalRole,
                        RefreshToken, ResourceGrant, Role, RolePermission,
                        SsoConnection, SsoState, QueryLog, TENANT_STATUS_ACTIVE,
                        TENANT_STATUS_SUSPENDED, User, utcnow)
from . import vectorstore

#: Tables deleted (in this order) when a workspace is removed. Rows keyed
#: indirectly (RolePermission → Role, GroupMember → Group) are handled first.
TENANT_SCOPED_MODELS = [
    QueryLog, Document, ModelConnector, ConnectorSyncRun, DataConnector,
    ResourceGrant, PermissionGrant, PrincipalRole, GroupMember, Group,
    RolePermission, Role, ApiKey, SsoConnection, SsoState, ActivityLog, AuditLog,
]


def revoke_tenant_sessions(db, tenant_id: int) -> int:
    """Revoke every refresh token held by a workspace's users. Returns the count."""
    uids = [u.id for u in db.query(User.id).filter(User.tenant_id == tenant_id)]
    if not uids:
        return 0
    n = (db.query(RefreshToken)
         .filter(RefreshToken.user_id.in_(uids), RefreshToken.revoked == 0)
         .update({"revoked": 1}, synchronize_session=False))
    return int(n or 0)


def set_status(db, tenant, *, status: str, reason: str = "") -> int:
    """Flip a workspace between 'active' and 'suspended'. On suspend, live
    sessions are revoked. Returns the number of sessions revoked."""
    tenant.status = status
    if status == TENANT_STATUS_SUSPENDED:
        tenant.suspended_at = utcnow()
        tenant.suspended_reason = (reason or "")[:500]
        revoked = revoke_tenant_sessions(db, tenant.id)
    else:
        tenant.suspended_at = None
        tenant.suspended_reason = ""
        revoked = 0
    db.merge(tenant)
    db.commit()
    return revoked


def purge_tenant_data(db, tenant) -> dict:
    """Delete a workspace and everything scoped to it. Returns a per-table
    tally (also written into the audit entry's meta)."""
    slug, tid = tenant.slug, tenant.id
    try:
        vectorstore.drop_tenant(slug)
    except Exception:                                    # best-effort; DB is source of truth
        pass

    tally: dict[str, int] = {}
    for model in TENANT_SCOPED_MODELS:
        if model is RolePermission:
            role_ids = [r.id for r in db.query(Role.id).filter(Role.tenant_id == tid)]
            n = (db.query(RolePermission)
                 .filter(RolePermission.role_id.in_(role_ids))
                 .delete(synchronize_session=False)) if role_ids else 0
        elif model is GroupMember:
            group_ids = [g.id for g in db.query(Group.id).filter(Group.tenant_id == tid)]
            n = (db.query(GroupMember)
                 .filter(GroupMember.group_id.in_(group_ids))
                 .delete(synchronize_session=False)) if group_ids else 0
        else:
            n = db.query(model).filter(model.tenant_id == tid).delete(
                synchronize_session=False)
        if n:
            tally[model.__tablename__] = int(n)

    # Users last (roles/grants referenced them), then refresh tokens they held.
    uids = [u.id for u in db.query(User.id).filter(User.tenant_id == tid)]
    if uids:
        tally["refresh_tokens"] = int(
            db.query(RefreshToken).filter(RefreshToken.user_id.in_(uids))
            .delete(synchronize_session=False) or 0)
        tally["users"] = int(
            db.query(User).filter(User.tenant_id == tid)
            .delete(synchronize_session=False) or 0)

    db.delete(tenant)
    db.commit()
    return tally


def tenant_detail(db, tenant, *, entitlements: dict | None = None) -> dict:
    s = tenant.settings_json or {}
    return {
        "id": tenant.id, "slug": tenant.slug, "name": tenant.name,
        "status": tenant.status or TENANT_STATUS_ACTIVE,
        "suspended_at": tenant.suspended_at.isoformat() if tenant.suspended_at else None,
        "suspended_reason": tenant.suspended_reason or None,
        "api_key": tenant.api_key,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "counts": {
            "users": db.query(User).filter(User.tenant_id == tenant.id).count(),
            "documents": db.query(Document).filter(Document.tenant_id == tenant.id).count(),
            "api_keys": db.query(ApiKey).filter(ApiKey.tenant_id == tenant.id,
                                                ApiKey.revoked == 0).count(),
            "custom_roles": db.query(Role).filter(Role.tenant_id == tenant.id).count(),
            "queries": db.query(QueryLog).filter(QueryLog.tenant_id == tenant.id).count(),
        },
        "entitlements": entitlements or {},
        "settings_overrides": s,
    }
