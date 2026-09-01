"""Authorisation layer.

Every request resolves to a Principal — {user?, role, tenant?} — through one
of two doors:

  * Bearer JWT (Authorization header)  → human users: member, tenant_admin,
    superadmin. The tenant is read from the verified token, NEVER from the
    request, which is what makes cross-tenant access structurally impossible.
  * X-API-Key                          → tenant-scoped service account for
    machine integrations. Treated as tenant_admin for content operations but
    cannot manage users.

Route guards are built from the capability model in ``app.rbac``:

    require(Permission.X, ...)   FastAPI dependency; 403 unless the principal's
                                 role holds every listed permission. Returns the
                                 Principal. ``tenant_required=True`` (default)
                                 also 400s when there is no workspace context.
    tenant_ctx(Permission.X)     Same check, but the dependency resolves to the
                                 Tenant directly (handy for existing route
                                 bodies that expect ``tenant=Depends(...)``).

The older names (``require_member``, ``require_tenant_admin``, ``get_tenant`` …)
are kept as thin aliases so existing routers keep working.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from .config import get_settings
from .database import (ApiKey, ROLE_SERVICE, ROLE_SUPERADMIN, SessionLocal,
                       Tenant, User, utcnow)
from .rbac import (Permission, WORKSPACE_PERMISSIONS, has_permission,
                   missing_permissions)
from .security import decode_access_token, hash_api_key


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@dataclass
class Principal:
    role: str
    user: User | None = None             # None for service (API key) principals
    tenant: Tenant | None = None         # None for superadmin
    # Effective permission set: built-in role ∪ custom roles ∪ grants − denies.
    # Resolved once per request in get_principal; falls back to the built-in
    # matrix for principals created outside a request.
    perms: frozenset[str] = frozenset()

    @property
    def email(self) -> str:
        return self.user.email if self.user else "api-key"

    @property
    def user_id(self) -> int | None:
        return self.user.id if self.user else None

    def can(self, permission: str) -> bool:
        if self.perms:
            return permission in self.perms
        return has_permission(self.role, permission)


def get_principal(authorization: str = Header(default=""),
                  x_api_key: str = Header(default=""),
                  x_tenant_key: str = Header(default=""),
                  db=Depends(get_db)) -> Principal:
    # Door 1: Bearer JWT
    if authorization.startswith("Bearer "):
        payload = decode_access_token(authorization[7:].strip())
        if not payload:
            raise HTTPException(401, "Invalid or expired token")
        user = db.get(User, int(payload["sub"]))
        if not user or not user.is_active:
            raise HTTPException(401, "Account is disabled")
        if payload.get("pwv") != user.password_version:
            raise HTTPException(401, "Session invalidated — please sign in again")
        tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
        if user.role != ROLE_SUPERADMIN and not tenant:
            raise HTTPException(401, "Account is not attached to a workspace")
        principal = Principal(role=user.role, user=user, tenant=tenant,
                              perms=_resolve_perms(db, user.role, user))
        _bind_observability(principal)
        return principal

    # Door 2: tenant service key. Prefer the hashed, revocable ApiKey table;
    # fall back to the legacy single plaintext Tenant.api_key.
    service_key = (x_api_key or x_tenant_key).strip()
    if service_key:
        tenant = _resolve_api_key(db, service_key)
        if not tenant:
            raise HTTPException(401, "Invalid or expired API key")
        principal = Principal(role=ROLE_SERVICE, tenant=tenant,
                              perms=_resolve_perms(db, ROLE_SERVICE, None))
        _bind_observability(principal)
        return principal

    raise HTTPException(401, "Not authenticated")


def _resolve_api_key(db, raw: str) -> Tenant | None:
    row = (db.query(ApiKey)
           .filter(ApiKey.key_hash == hash_api_key(raw), ApiKey.revoked == 0)
           .first())
    if row:
        if row.expires_at:
            exp = row.expires_at
            if exp.tzinfo is None:
                import datetime as _dt
                exp = exp.replace(tzinfo=_dt.timezone.utc)
            import datetime as _dt
            if exp < _dt.datetime.now(_dt.timezone.utc):
                return None
        row.last_used_at = utcnow()
        db.commit()
        return db.get(Tenant, row.tenant_id)
    return db.query(Tenant).filter(Tenant.api_key == raw).first()  # legacy


def _resolve_perms(db, role: str, user) -> frozenset[str]:
    """Effective permission set. Isolated so a resolution bug degrades to the
    built-in matrix rather than 500-ing every request."""
    try:
        from .authz import effective_permissions
        return effective_permissions(db, role, user)
    except Exception:                       # pragma: no cover — defensive
        import logging
        logging.getLogger("knowledgedesk.auth").exception("perm resolution failed")
        from .rbac import ROLE_PERMISSIONS
        return frozenset(ROLE_PERMISSIONS.get(role, frozenset()))


def _bind_observability(principal: "Principal") -> None:
    """Attach tenant/actor to the observability context so events and spans
    emitted by this request are correlated. Best-effort only."""
    try:
        from . import observability as obs
        obs.bind(tenant=principal.tenant.slug if principal.tenant else None,
                 actor=principal.email)
    except Exception:
        pass


# ── Permission guards ───────────────────────────────────────────────

def require(*permissions: str, tenant_required: bool = True):
    """Build a dependency that enforces every listed permission.

    Returns the Principal on success. ``tenant_required`` (default True) also
    rejects principals without a workspace — every workspace permission needs
    one, and it keeps route bodies free of ``if not principal.tenant`` checks.
    """
    needed = frozenset(permissions)
    if not needed:
        raise ValueError("require() needs at least one permission")

    def guard(principal: Principal = Depends(get_principal)) -> Principal:
        # principal.perms already folds in custom roles, grants and denies.
        held = principal.perms or frozenset()
        missing = needed - held if held else missing_permissions(principal.role, needed)
        if missing:
            if principal.role == ROLE_SUPERADMIN and needed <= WORKSPACE_PERMISSIONS:
                raise HTTPException(
                    403, "Platform administrator has no access to workspace content")
            raise HTTPException(403, f"Missing permission: {sorted(missing)[0]}")
        if tenant_required and principal.tenant is None:
            raise HTTPException(400, "Workspace context required")
        return principal

    return guard


def tenant_ctx(*permissions: str):
    """Like ``require`` but the dependency resolves to the Tenant itself."""
    dep = require(*permissions)

    def resolve(principal: Principal = Depends(dep)) -> Tenant:
        return principal.tenant

    return resolve


# ── Backwards-compatible aliases ───────────────────────────────────

def require_member(principal: Principal = Depends(get_principal)) -> Principal:
    """Any authenticated workspace principal (member, tenant_admin or service)."""
    if principal.role == ROLE_SUPERADMIN:
        raise HTTPException(403, "Platform administrator has no access to workspace content")
    if principal.tenant is None:
        raise HTTPException(400, "Workspace context required")
    return principal


require_tenant_admin = require(Permission.DOC_WRITE_TENANT)


def require_superadmin(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != ROLE_SUPERADMIN:
        raise HTTPException(403, "Platform administrator permission required")
    return principal


require_user_manager = require(Permission.USER_MANAGE, tenant_required=False)


def get_tenant(principal: Principal = Depends(require_member)) -> Tenant:
    """Tenant of the authenticated principal — always from the token/key."""
    return principal.tenant


def get_tenant_admin(principal: Principal = Depends(require_tenant_admin)) -> Tenant:
    return principal.tenant


# Legacy admin-key guard (kept for backwards-compatible scripts; superadmin
# JWTs are the primary path).
def require_admin(x_admin_key: str = Header(default=""),
                  authorization: str = Header(default=""),
                  db=Depends(get_db)) -> None:
    s = get_settings()
    if (s.auth_legacy_admin_key_enabled and x_admin_key
            and x_admin_key == s.admin_api_key):
        return
    if authorization.startswith("Bearer "):
        payload = decode_access_token(authorization[7:].strip())
        if payload and payload.get("role") == ROLE_SUPERADMIN:
            user = db.get(User, int(payload["sub"]))
            if user and user.is_active and payload.get("pwv") == user.password_version:
                return
    raise HTTPException(401, "Platform administrator permission required")
