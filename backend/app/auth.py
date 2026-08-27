"""Authorisation layer.

Every request resolves to a Principal — {user?, role, tenant?} — through one
of two doors:

  * Bearer JWT (Authorization header)  → human users: member, tenant_admin,
    superadmin. The tenant is read from the verified token, NEVER from the
    request, which is what makes cross-tenant access structurally impossible.
  * X-API-Key                          → tenant-scoped service account for
    machine integrations. Treated as tenant_admin for content operations but
    cannot manage users.

Route guards compose from these dependencies:

    require_member        any authenticated tenant principal
    require_tenant_admin  tenant_admin (or service key)
    require_superadmin    platform operator only (humans, never API keys)

`get_tenant` keeps its original name so existing routers keep working — it now
returns the tenant of whichever principal authenticated.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from .config import get_settings
from .database import (ROLE_MEMBER, ROLE_RANK, ROLE_SUPERADMIN,
                       ROLE_TENANT_ADMIN, SessionLocal, Tenant, User)
from .security import decode_access_token

ROLE_SERVICE = "service"          # API-key principal; tenant_admin-equivalent for content


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

    @property
    def email(self) -> str:
        return self.user.email if self.user else "api-key"

    def content_rank(self) -> int:
        """Rank used for tenant-content authorisation."""
        if self.role == ROLE_SERVICE:
            return ROLE_RANK[ROLE_TENANT_ADMIN]
        return ROLE_RANK.get(self.role, 0)


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
        return Principal(role=user.role, user=user, tenant=tenant)

    # Door 2: tenant service key. X-API-Key is canonical; X-Tenant-Key is
    # accepted for backwards-compatible demo scripts and earlier README examples.
    service_key = x_api_key or x_tenant_key
    if service_key:
        tenant = db.query(Tenant).filter(Tenant.api_key == service_key).first()
        if not tenant:
            raise HTTPException(401, "Invalid API key")
        return Principal(role=ROLE_SERVICE, tenant=tenant)

    raise HTTPException(401, "Not authenticated")


def _require_content_role(min_role: str):
    min_rank = ROLE_RANK[min_role]

    def guard(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role == ROLE_SUPERADMIN:
            # Deliberate: the platform operator cannot touch tenant content.
            raise HTTPException(
                403, "Superadmin has no access to workspace content")
        if principal.content_rank() < min_rank:
            raise HTTPException(403, "Workspace admin permission required")
        return principal

    return guard


require_member = _require_content_role(ROLE_MEMBER)
require_tenant_admin = _require_content_role(ROLE_TENANT_ADMIN)


def require_superadmin(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != ROLE_SUPERADMIN:
        raise HTTPException(403, "Platform administrator permission required")
    return principal


def require_user_manager(principal: Principal = Depends(get_principal)) -> Principal:
    """tenant_admin (own tenant) or superadmin. API keys cannot manage users."""
    if principal.role in (ROLE_TENANT_ADMIN, ROLE_SUPERADMIN):
        return principal
    raise HTTPException(403, "User management requires an admin account")


# ── Tenant resolution for content routes ────────────────────────────

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
    if x_admin_key and x_admin_key == get_settings().admin_api_key:
        return
    if authorization.startswith("Bearer "):
        payload = decode_access_token(authorization[7:].strip())
        if payload and payload.get("role") == ROLE_SUPERADMIN:
            user = db.get(User, int(payload["sub"]))
            if user and user.is_active and payload.get("pwv") == user.password_version:
                return
    raise HTTPException(401, "Platform administrator permission required")
