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

from fastapi import Depends, Header, HTTPException, Request

from .config import get_settings
from .database import (ApiKey, ROLE_SERVICE, ROLE_SUPERADMIN, SessionLocal,
                       TENANT_STATUS_ACTIVE, Tenant, User, utcnow)
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
    # Identity of the API key behind a service principal (None for humans and
    # the legacy plaintext Tenant.api_key). Recorded in audit/activity rows so a
    # machine action is attributable to a specific, revocable key.
    api_key_id: int | None = None
    api_key_name: str = ""
    api_key_prefix: str = ""

    @property
    def email(self) -> str:
        return self.user.email if self.user else "api-key"

    @property
    def actor_label(self) -> str:
        """How this principal is named in the audit/activity trail — a human's
        email, or ``api-key:<name>`` / ``api-key:<prefix>`` for a service key."""
        if self.user:
            return self.user.email
        if self.api_key_name:
            return f"api-key:{self.api_key_name}"
        if self.api_key_prefix:
            return f"api-key:{self.api_key_prefix}"
        return "api-key"

    @property
    def user_id(self) -> int | None:
        return self.user.id if self.user else None

    def can(self, permission: str) -> bool:
        if self.perms:
            return permission in self.perms
        return has_permission(self.role, permission)


def _reject(reason: str, status: int, message: str) -> None:
    """Emit a security event for a rejected credential, then 401/403."""
    try:
        from . import observability as obs
        obs.count("auth.token.rejected", reason=reason)
        obs.event("auth.token.rejected", level="warn", reason=reason)
    except Exception:
        pass
    raise HTTPException(status, message)


def _stash_actor(request: Request | None, principal: "Principal") -> None:
    """Put a light identity dict on the ASGI scope so the activity middleware
    (which runs outside the DI/session scope) can attribute the request without
    touching a detached ORM object."""
    if request is None:
        return
    try:
        request.scope["kd_actor"] = {
            "user_id": principal.user_id,
            "email": principal.actor_label,
            "role": principal.role,
            "tenant_id": principal.tenant.id if principal.tenant else None,
            "api_key_id": principal.api_key_id,
            "api_key_name": principal.api_key_name,
        }
    except Exception:                                    # pragma: no cover
        pass


def get_principal(request: Request = None,  # noqa: B008 — FastAPI injects it
                  authorization: str = Header(default=""),
                  x_api_key: str = Header(default=""),
                  x_tenant_key: str = Header(default=""),
                  db=Depends(get_db)) -> Principal:
    # Door 1: Bearer JWT
    if authorization.startswith("Bearer "):
        payload = decode_access_token(authorization[7:].strip())
        if not payload:
            _reject("bad_token", 401, "Invalid or expired token")
        user = db.get(User, int(payload["sub"]))
        if not user or not user.is_active:
            _reject("disabled_account", 401, "Account is disabled")
        if payload.get("pwv") != user.password_version:
            _reject("stale_password_version", 401, "Session invalidated — please sign in again")
        tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
        if user.role != ROLE_SUPERADMIN and not tenant:
            _reject("no_workspace", 401, "Account is not attached to a workspace")
        if (user.role != ROLE_SUPERADMIN and tenant
                and tenant.status != TENANT_STATUS_ACTIVE):
            _reject("tenant_suspended", 403, "This workspace is suspended")
        principal = Principal(role=user.role, user=user, tenant=tenant,
                              perms=_resolve_perms(db, user.role, user))
        _bind_observability(principal)
        _stash_actor(request, principal)
        return principal

    # Door 2: tenant service key. Prefer the hashed, revocable ApiKey table;
    # fall back to the legacy single plaintext Tenant.api_key.
    service_key = (x_api_key or x_tenant_key).strip()
    if service_key:
        tenant, key_row = _resolve_api_key(db, service_key)
        if not tenant:
            _reject("bad_api_key", 401, "Invalid or expired API key")
        if tenant.status != TENANT_STATUS_ACTIVE:
            _reject("tenant_suspended", 403, "This workspace is suspended")
        principal = Principal(role=ROLE_SERVICE, tenant=tenant,
                              perms=_resolve_perms(db, ROLE_SERVICE, None),
                              api_key_id=key_row.id if key_row else None,
                              api_key_name=key_row.name if key_row else "",
                              api_key_prefix=key_row.prefix if key_row else "")
        _bind_observability(principal)
        _stash_actor(request, principal)
        return principal

    raise HTTPException(401, "Not authenticated")


def _resolve_api_key(db, raw: str) -> "tuple[Tenant | None, ApiKey | None]":
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
                return None, None
        row.last_used_at = utcnow()
        db.commit()
        return db.get(Tenant, row.tenant_id), row
    legacy = db.query(Tenant).filter(Tenant.api_key == raw).first()  # legacy
    return legacy, None


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


def log_denied(principal: "Principal", permission: str) -> None:
    """Security event for an authorization denial. Feeds the events sinks / SIEM.
    Identity is passed explicitly (sync deps don't propagate obs context)."""
    try:
        from . import observability as obs
        tenant = principal.tenant.slug if principal.tenant else None
        obs.count("authz.denied", permission=permission, role=principal.role)
        obs.event("authz.denied", level="warn", permission=permission,
                  role=principal.role, actor=principal.email, tenant=tenant)
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
            log_denied(principal, sorted(missing)[0])
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
        log_denied(principal, "workspace.content")
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
    if s.auth_legacy_admin_key_enabled and x_admin_key:
        from .secret_resolver import resolve_secret
        if x_admin_key == (resolve_secret(s.admin_api_key) or s.admin_api_key):
            return
    if authorization.startswith("Bearer "):
        payload = decode_access_token(authorization[7:].strip())
        if payload and payload.get("role") == ROLE_SUPERADMIN:
            user = db.get(User, int(payload["sub"]))
            if user and user.is_active and payload.get("pwv") == user.password_version:
                return
    raise HTTPException(401, "Platform administrator permission required")
