"""SSO sign-in (generic OIDC) — the ``sso`` subscription entitlement.

Works with any OIDC provider (Google, Okta, Microsoft Entra, Auth0, Keycloak).
Per-tenant configuration lives in ``SsoConnection`` and is managed from
``/api/access/sso`` (see routers/access.py). This module is the runtime flow:

  lookup  → the login page asks "is SSO available for this email/workspace?"
  start   → 302 to the IdP (auth-code + PKCE, signed state)
  callback→ verify id_token, JIT-provision / match the user, mint a session,
            302 back to the SPA with the tokens in the URL fragment.

When the entitlement is off, `lookup` reports `available: false` and `start`
returns 402 — the frontend then shows SSO as an upgrade.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import authn
from .. import observability as obs
from ..auth import get_db
from ..config import get_settings
from ..crypto import decrypt_secrets
from ..database import (ROLE_MEMBER, SsoConnection, SsoState, Tenant, User,
                        utcnow)
from ..services import audit
from .auth_routes import mint_session

log = logging.getLogger("knowledgedesk.sso")
router = APIRouter(prefix="/api/auth/sso", tags=["auth"])


def _callback_uri(request: Request) -> str:
    """The redirect URI registered with the IdP. Prefer the configured public
    origin (correct behind the TLS proxy); fall back to the request's own URL."""
    base = get_settings().public_base_url.strip().rstrip("/")
    if base:
        return f"{base}/api/auth/sso/callback"
    return str(request.url_for("sso_callback"))


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _connection_for_email(db, email: str) -> SsoConnection | None:
    domain = email.split("@")[-1].lower().strip()
    if not domain:
        return None
    for conn in db.query(SsoConnection).filter(SsoConnection.is_active == True).all():  # noqa: E712
        doms = [d.lower() for d in (conn.allowed_domains or [])]
        if not doms or domain in doms:
            return conn
    return None


def _connection_for_workspace(db, slug: str) -> SsoConnection | None:
    tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
    if not tenant:
        return None
    return (db.query(SsoConnection)
            .filter(SsoConnection.tenant_id == tenant.id,
                    SsoConnection.is_active == True).first())  # noqa: E712


@router.get("/lookup")
def lookup(email: str | None = None, workspace: str | None = None, db=Depends(get_db)):
    conn = (_connection_for_email(db, email) if email
            else _connection_for_workspace(db, workspace) if workspace else None)
    if not conn:
        return {"available": False}
    tenant = db.get(Tenant, conn.tenant_id)
    entitled = authn.entitlement_enabled(tenant, "sso")
    return {
        "available": bool(entitled),
        "entitled": entitled,
        "display_name": conn.display_name or "SSO",
        "workspace": tenant.slug,
        "start_url": f"/api/auth/sso/start?workspace={tenant.slug}",
    }


@router.get("/start")
def start(request: Request, workspace: str, db=Depends(get_db)):
    conn = _connection_for_workspace(db, workspace)
    if not conn:
        raise HTTPException(404, "No SSO configured for that workspace")
    tenant = db.get(Tenant, conn.tenant_id)
    if not authn.entitlement_enabled(tenant, "sso"):
        raise HTTPException(402, "Single sign-on is not included in this workspace's plan")
    if not (conn.issuer and conn.client_id):
        raise HTTPException(409, "SSO connection is incomplete — set issuer and client id")

    try:
        disco = authn.oidc_discover(conn.issuer)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Could not reach the identity provider: {exc}") from exc

    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    redirect_uri = _callback_uri(request)
    db.add(SsoState(state=state, tenant_id=tenant.id, code_verifier=verifier,
                    redirect_uri=redirect_uri))
    db.commit()
    url = authn.oidc_authorize_url(disco, conn.client_id, redirect_uri, state, challenge)
    obs.event("auth.sso.start", tenant=tenant.slug)
    return RedirectResponse(url, status_code=302)


@router.get("/callback", name="sso_callback")
def callback(request: Request, code: str | None = None, state: str | None = None,
             error: str | None = None, db=Depends(get_db)):
    front = get_settings().app_base_url
    if error or not code or not state:
        return RedirectResponse(f"{front}/login?sso_error={error or 'cancelled'}", status_code=302)

    st = db.query(SsoState).filter(SsoState.state == state).first()
    if not st:
        return RedirectResponse(f"{front}/login?sso_error=bad_state", status_code=302)
    age = (utcnow() - (st.created_at or utcnow())).total_seconds()
    db.delete(st)
    db.commit()
    if age > 600:
        return RedirectResponse(f"{front}/login?sso_error=expired", status_code=302)

    conn = db.query(SsoConnection).filter(SsoConnection.tenant_id == st.tenant_id).first()
    tenant = db.get(Tenant, st.tenant_id)
    if not conn or not tenant or not authn.entitlement_enabled(tenant, "sso"):
        return RedirectResponse(f"{front}/login?sso_error=unavailable", status_code=302)

    secret = decrypt_secrets(conn.secret_encrypted, resolve=True).get("client_secret", "")
    try:
        disco = authn.oidc_discover(conn.issuer)
        tok = authn.oidc_exchange_code(disco, conn.client_id, secret, code,
                                       st.redirect_uri, st.code_verifier)
        claims = authn.oidc_verify_id_token(disco, tok["id_token"], conn.client_id, conn.issuer)
    except Exception as exc:  # noqa: BLE001
        log.warning("SSO callback failed: %s", exc)
        return RedirectResponse(f"{front}/login?sso_error=verify_failed", status_code=302)

    email = (claims.get("email") or "").lower().strip()
    if not email or (claims.get("email_verified") is False):
        return RedirectResponse(f"{front}/login?sso_error=no_verified_email", status_code=302)
    domain = email.split("@")[-1]
    doms = [d.lower() for d in (conn.allowed_domains or [])]
    if doms and domain not in doms:
        return RedirectResponse(f"{front}/login?sso_error=domain_not_allowed", status_code=302)

    user = db.query(User).filter(User.email == email).first()
    if user and user.tenant_id != tenant.id:
        return RedirectResponse(f"{front}/login?sso_error=account_in_another_workspace", status_code=302)
    if not user:
        user = User(email=email, full_name=claims.get("name", ""),
                    password_hash="!sso-no-password", role=conn.default_role or ROLE_MEMBER,
                    tenant_id=tenant.id, email_verified=1, force_password_change=0,
                    auth_provider="sso")
        db.add(user)
        db.commit()
        db.refresh(user)
        audit.record(db, action="user.provisioned_sso", actor_email=email,
                     tenant_id=tenant.id, detail="JIT via SSO")
    if not user.is_active:
        return RedirectResponse(f"{front}/login?sso_error=account_disabled", status_code=302)

    user.last_login_at = utcnow()
    user.email_verified = 1
    db.commit()
    audit.record(db, action="auth.login", actor_email=email, actor_role=user.role,
                 tenant_id=tenant.id, detail="sso")
    obs.count("auth.logins", outcome="success", role=user.role, method="sso")
    obs.event("auth.login", actor=email, role=user.role, tenant=tenant.slug, method="sso")

    session = mint_session(db, user, ip=request.client.host if request.client else "",
                           user_agent=request.headers.get("user-agent", ""), label="SSO")
    frag = urlencode({"access": session["access_token"],
                      "refresh": session["refresh_token"]})
    return RedirectResponse(f"{front}/login/sso/complete#{frag}", status_code=302)
