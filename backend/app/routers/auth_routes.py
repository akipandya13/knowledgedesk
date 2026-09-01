"""Authentication endpoints.

Login (rate-limited, optional TOTP step), token refresh/rotation, logout,
self-service password reset + email verification, TOTP enrolment, and session
(refresh-token) management. SSO lives in ``routers/sso.py``.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import authn
from .. import observability as obs
from .. import security
from ..auth import Principal, get_db, get_principal
from ..config import get_settings
from ..crypto import decrypt_secrets, encrypt_secrets
from ..database import (AuthToken, PasswordHistory, RefreshToken,
                        ROLE_SUPERADMIN, TENANT_STATUS_ACTIVE, Tenant, User,
                        utcnow)
from ..services import activity, audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

GENERIC_LOGIN_ERROR = "Incorrect email or password"


# ── request models ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class MfaLoginRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=4, max_length=32)


class RefreshRequest(BaseModel):
    refresh_token: str | None = None          # optional when the httpOnly cookie is used


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(max_length=200)


class ForgotRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResetRequest(BaseModel):
    token: str
    new_password: str = Field(max_length=200)


class TokenOnly(BaseModel):
    token: str


class MfaEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class MfaDisableRequest(BaseModel):
    password: str | None = None
    code: str | None = None


# ── helpers ───────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else "") or (request.client.host if request.client else "")


def _user_out(user: User, tenant: Tenant | None) -> dict:
    return {
        "id": user.id, "email": user.email, "full_name": user.full_name,
        "role": user.role,
        "tenant": ({"slug": tenant.slug, "name": tenant.name} if tenant else None),
        "force_password_change": bool(user.force_password_change),
        "mfa_enabled": bool(user.mfa_enabled),
        "email_verified": bool(user.email_verified),
        "auth_provider": user.auth_provider or "password",
    }


def _active_sessions(db, user_id: int):
    now = dt.datetime.now(dt.timezone.utc)
    rows = (db.query(RefreshToken)
            .filter(RefreshToken.user_id == user_id, RefreshToken.revoked == 0)
            .order_by(RefreshToken.session_started_at.asc(), RefreshToken.created_at.asc())
            .all())
    live = []
    for r in rows:
        exp = _aware(r.expires_at)
        if exp and exp < now:
            continue
        live.append(r)
    return live


def _aware(v):
    return v.replace(tzinfo=dt.timezone.utc) if v is not None and v.tzinfo is None else v


def mint_session(db, user: User, *, ip: str = "", user_agent: str = "",
                 label: str = "", session_started_at=None) -> dict:
    """Create an access token + a stored refresh token. Used by password login,
    MFA completion, refresh rotation and SSO callback. Enforces the per-user
    concurrent-session cap by evicting the oldest chain."""
    s = get_settings()
    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
    access = security.create_access_token(
        user_id=user.id, email=user.email, role=user.role,
        tenant_id=user.tenant_id, tenant_slug=tenant.slug if tenant else None,
        password_version=user.password_version)
    raw_refresh, token_hash = security.new_refresh_token()
    now = utcnow()
    db.add(RefreshToken(user_id=user.id, token_hash=token_hash,
                        expires_at=security.refresh_expiry(),
                        user_agent=(user_agent or "")[:400], ip=ip, label=label,
                        session_started_at=session_started_at or now, last_used_at=now))
    db.commit()

    live = _active_sessions(db, user.id)
    if len(live) > max(1, s.auth_max_sessions_per_user):
        for stale in live[: len(live) - s.auth_max_sessions_per_user]:
            stale.revoked = 1
        db.commit()
        obs.count("auth.session.evicted", n=len(live) - s.auth_max_sessions_per_user)

    return {
        "access_token": access, "refresh_token": raw_refresh, "token_type": "bearer",
        "expires_in": s.access_token_minutes * 60,
        "user": _user_out(user, tenant),
    }


def _set_refresh_cookie(response: Response | None, token: str) -> None:
    s = get_settings()
    if response is not None and s.auth_refresh_cookie:
        response.set_cookie("kd_refresh", token, httponly=True, samesite="lax",
                            secure=s.auth_cookie_secure,
                            max_age=s.refresh_token_days * 86400, path="/api/auth")


def _read_refresh(req: RefreshRequest | None, cookie: str | None) -> str:
    raw = ((req.refresh_token if req else None) or cookie or "").strip()
    if not raw:
        raise HTTPException(401, "No refresh token supplied")
    return raw


def _issue_session(db, user: User, request: Request, response: Response | None,
                   label: str = "", session_started_at=None) -> dict:
    out = mint_session(db, user, ip=_client_ip(request),
                       user_agent=request.headers.get("user-agent", ""), label=label,
                       session_started_at=session_started_at)
    _set_refresh_cookie(response, out["refresh_token"])
    return out


def _totp_secret(user: User) -> str:
    return decrypt_secrets(user.mfa_secret_encrypted).get("totp", "")


def _record_password(db, user: User, new_plain: str) -> None:
    """Set a new password: hash, bump version, record history, revoke sessions."""
    s = get_settings()
    db.add(PasswordHistory(user_id=user.id, password_hash=user.password_hash))
    keep = (db.query(PasswordHistory).filter(PasswordHistory.user_id == user.id)
            .order_by(PasswordHistory.created_at.desc()).all())
    for stale in keep[s.auth_pw_history:]:
        db.delete(stale)
    user.password_hash = security.hash_password(new_plain)
    user.password_version += 1
    user.password_changed_at = utcnow()
    user.force_password_change = 0
    db.query(RefreshToken).filter(RefreshToken.user_id == user.id).update({"revoked": 1})


def _history_hashes(db, user: User) -> list[str]:
    rows = (db.query(PasswordHistory).filter(PasswordHistory.user_id == user.id)
            .order_by(PasswordHistory.created_at.desc())
            .limit(get_settings().auth_pw_history).all())
    return [user.password_hash] + [r.password_hash for r in rows]


# ── login ─────────────────────────────────────────────────────────

@router.post("/login")
def login(req: LoginRequest, request: Request, response: Response, db=Depends(get_db)):
    s = get_settings()
    email = req.email.strip().lower()
    ip = _client_ip(request)

    throttled = authn.check_login_rate(ip, email)
    if throttled:
        obs.count("auth.logins", outcome="throttled")
        raise HTTPException(429, throttled)

    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active:
        audit.record(db, action="auth.login.failed", actor_email=email,
                     detail="unknown or disabled account")
        obs.count("auth.logins", outcome="failed", reason="unknown_or_disabled")
        obs.event("auth.login.failed", level="warn", email=email, reason="unknown_or_disabled")
        raise HTTPException(401, GENERIC_LOGIN_ERROR)

    remaining = security.lockout_remaining_minutes(user.locked_until)
    if remaining:
        raise HTTPException(423, f"Account locked after repeated failures — try again in {remaining} min")

    if not security.verify_password(req.password, user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= s.login_max_failures:
            user.locked_until = (dt.datetime.now(dt.timezone.utc)
                                 + dt.timedelta(minutes=s.login_lockout_minutes))
            user.failed_logins = 0
        db.commit()
        audit.record(db, action="auth.login.failed", actor_email=email,
                     tenant_id=user.tenant_id, detail="wrong password")
        obs.count("auth.logins", outcome="failed", reason="bad_password")
        obs.event("auth.login.failed", level="warn", email=email, reason="bad_password",
                  locked=bool(user.locked_until))
        raise HTTPException(401, GENERIC_LOGIN_ERROR)

    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
    if (user.role != ROLE_SUPERADMIN and tenant
            and tenant.status != TENANT_STATUS_ACTIVE):
        raise HTTPException(403, "This workspace is suspended. Contact your platform administrator.")
    if _requires_verified(tenant) and not user.email_verified:
        raise HTTPException(403, "Verify your email address before signing in — check your inbox.")

    user.failed_logins = 0
    user.locked_until = None

    # Password expiry (opt-in): force a change on next step, don't block sign-in.
    if s.auth_pw_max_age_days > 0 and not user.force_password_change:
        changed = _aware(user.password_changed_at) or dt.datetime.now(dt.timezone.utc)
        if (dt.datetime.now(dt.timezone.utc) - changed).days >= s.auth_pw_max_age_days:
            user.force_password_change = 1
            audit.record(db, action="auth.password.expired", actor_email=user.email,
                         tenant_id=user.tenant_id)
            obs.event("auth.password.expired", level="warn", actor=user.email,
                      tenant=(user.tenant.slug if user.tenant else None))
    db.commit()
    authn.clear_login_rate(ip, email)

    if user.mfa_enabled:
        obs.event("auth.login.mfa_challenge", actor=user.email)
        return {"mfa_required": True, "mfa_token": security.create_mfa_token(user.id)}

    user.last_login_at = utcnow()
    db.commit()
    audit.record(db, action="auth.login", actor_email=user.email,
                 actor_role=user.role, tenant_id=user.tenant_id)
    activity.record(db, action="session.start", category="auth", user_id=user.id,
                    actor_email=user.email, actor_role=user.role,
                    tenant_id=user.tenant_id, meta={"mfa": False})
    obs.count("auth.logins", outcome="success", role=user.role, mfa="false")
    obs.event("auth.login", actor=user.email,
              tenant=(tenant.slug if tenant else None), role=user.role)
    return _issue_session(db, user, request, response)


@router.post("/login/mfa")
def login_mfa(req: MfaLoginRequest, request: Request, response: Response, db=Depends(get_db)):
    payload = security.decode_mfa_token(req.mfa_token)
    if not payload:
        raise HTTPException(401, "MFA session expired — sign in again")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active or not user.mfa_enabled:
        raise HTTPException(401, "MFA session invalid")

    code = req.code.strip()
    ok = security.verify_totp(_totp_secret(user), code)
    if not ok:
        h = security.recovery_code_hash(code)
        codes = list(user.mfa_recovery_hashes or [])
        if h in codes:
            codes.remove(h)
            user.mfa_recovery_hashes = codes
            ok = True
            obs.event("auth.mfa.recovery_used", actor=user.email)
    if not ok:
        audit.record(db, action="auth.mfa.failed", actor_email=user.email,
                     tenant_id=user.tenant_id)
        obs.count("auth.logins", outcome="failed", reason="bad_mfa")
        raise HTTPException(401, "Invalid authentication code")

    user.last_login_at = utcnow()
    db.commit()
    audit.record(db, action="auth.login", actor_email=user.email,
                 actor_role=user.role, tenant_id=user.tenant_id, detail="mfa")
    activity.record(db, action="session.start", category="auth", user_id=user.id,
                    actor_email=user.email, actor_role=user.role,
                    tenant_id=user.tenant_id, meta={"mfa": True})
    obs.count("auth.logins", outcome="success", role=user.role, mfa="true")
    obs.event("auth.login", actor=user.email, role=user.role, mfa=True)
    return _issue_session(db, user, request, response)


@router.post("/refresh")
def refresh(request: Request, response: Response, req: RefreshRequest | None = None,
            kd_refresh: str | None = Cookie(default=None), db=Depends(get_db)):
    raw = _read_refresh(req, kd_refresh)
    row = db.query(RefreshToken).filter(
        RefreshToken.token_hash == security.hash_refresh_token(raw)).first()
    if not row:
        raise HTTPException(401, "Invalid refresh token")
    if row.revoked:
        db.query(RefreshToken).filter(RefreshToken.user_id == row.user_id).update({"revoked": 1})
        db.commit()
        audit.record(db, action="auth.refresh.reuse_detected",
                     detail=f"user_id={row.user_id} — all sessions revoked")
        obs.count("auth.refresh.reuse_detected")
        obs.event("auth.refresh.reuse_detected", level="error", user_id=row.user_id)
        raise HTTPException(401, "Session revoked — please sign in again")

    now = dt.datetime.now(dt.timezone.utc)
    expires = _aware(row.expires_at)
    if not expires or expires < now:
        raise HTTPException(401, "Refresh token expired — please sign in again")

    # Idle timeout: this refresh chain has not been used within the window.
    idle_since = _aware(row.last_used_at) or _aware(row.created_at) or now
    if (now - idle_since).total_seconds() > get_settings().auth_session_idle_hours * 3600:
        row.revoked = 1
        db.commit()
        obs.event("auth.session.timed_out", level="warn", reason="idle", user_id=row.user_id)
        raise HTTPException(401, "Session timed out from inactivity — sign in again")

    # Absolute cap: the whole session cannot outlive this, regardless of rotation.
    started = _aware(row.session_started_at) or _aware(row.created_at) or now
    if (now - started).total_seconds() > get_settings().auth_session_max_days * 86400:
        row.revoked = 1
        db.commit()
        obs.event("auth.session.timed_out", level="warn", reason="absolute", user_id=row.user_id)
        raise HTTPException(401, "Session expired — sign in again")

    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Account is disabled")
    if user.role != ROLE_SUPERADMIN and user.tenant_id:
        t = db.get(Tenant, user.tenant_id)
        if t and t.status != TENANT_STATUS_ACTIVE:
            row.revoked = 1
            db.commit()
            raise HTTPException(403, "This workspace is suspended.")

    row.revoked = 1
    db.commit()
    obs.event("auth.session.refreshed", actor=user.email)
    return _issue_session(db, user, request, response, label=row.label or "",
                          session_started_at=row.session_started_at)


@router.post("/logout")
def logout(response: Response, principal: Principal = Depends(get_principal),
           req: RefreshRequest | None = None,
           kd_refresh: str | None = Cookie(default=None), db=Depends(get_db)):
    raw = ((req.refresh_token if req else None) or kd_refresh or "").strip()
    if raw:
        token_hash = security.hash_refresh_token(raw)
        db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).update({"revoked": 1})
    if get_settings().auth_refresh_cookie:
        response.delete_cookie("kd_refresh", path="/api/auth")
    db.commit()
    audit.record(db, action="auth.logout", actor_email=principal.email,
                 actor_role=principal.role,
                 tenant_id=principal.tenant.id if principal.tenant else None)
    activity.record(db, action="session.end", category="auth", principal=principal)
    return {"ok": True}


@router.get("/me")
def me(principal: Principal = Depends(get_principal)):
    if principal.user is None:
        return {"id": None, "email": "api-key", "role": "service",
                "tenant": {"slug": principal.tenant.slug, "name": principal.tenant.name},
                "force_password_change": False, "mfa_enabled": False,
                "email_verified": True, "auth_provider": "api_key"}
    return _user_out(principal.user, principal.tenant)


# ── password: change / forgot / reset ─────────────────────────────

@router.post("/change-password")
def change_password(req: ChangePasswordRequest,
                    principal: Principal = Depends(get_principal), db=Depends(get_db)):
    user = principal.user
    if user is None:
        raise HTTPException(403, "API keys have no password")
    if not security.verify_password(req.current_password, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    problem = security.validate_password_policy(req.new_password, user.email,
                                                _history_hashes(db, user))
    if problem:
        raise HTTPException(400, problem)
    _record_password(db, user, req.new_password)
    db.commit()
    audit.record(db, action="auth.password_changed", actor_email=user.email,
                 actor_role=user.role, tenant_id=user.tenant_id)
    return {"ok": True, "note": "All sessions signed out — log in again"}


@router.post("/password/forgot")
def password_forgot(req: ForgotRequest, db=Depends(get_db)):
    email = req.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user and user.is_active:
        raw, h = security.new_email_token()
        db.add(AuthToken(user_id=user.id, purpose="reset_password", token_hash=h,
                         expires_at=utcnow() + dt.timedelta(hours=1)))
        db.commit()
        authn.send_email(email, "Reset your KnowledgeDesk password",
                         f"Reset your password (valid 1 hour):\n{authn.link('/reset-password?token=' + raw)}")
        audit.record(db, action="auth.password.reset_requested", actor_email=email,
                     tenant_id=user.tenant_id)
        obs.event("auth.password.reset_requested", actor=email)
    return {"ok": True, "note": "If that account exists, a reset link has been sent."}


@router.post("/password/reset")
def password_reset(req: ResetRequest, db=Depends(get_db)):
    row = _consume_token(db, req.token, "reset_password")
    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(400, "Account unavailable")
    problem = security.validate_password_policy(req.new_password, user.email,
                                                _history_hashes(db, user))
    if problem:
        raise HTTPException(400, problem)
    _record_password(db, user, req.new_password)
    user.failed_logins = 0
    user.locked_until = None
    user.email_verified = 1
    db.commit()
    audit.record(db, action="auth.password.reset", actor_email=user.email,
                 tenant_id=user.tenant_id)
    return {"ok": True, "note": "Password updated — sign in with your new password."}


# ── email verification ───────────────────────────────────────────

@router.post("/email/verify")
def email_verify(req: TokenOnly, db=Depends(get_db)):
    row = _consume_token(db, req.token, "verify_email")
    user = db.get(User, row.user_id)
    if user:
        user.email_verified = 1
        db.commit()
        audit.record(db, action="auth.email.verified", actor_email=user.email,
                     tenant_id=user.tenant_id)
    return {"ok": True}


@router.post("/email/resend")
def email_resend(principal: Principal = Depends(get_principal), db=Depends(get_db)):
    user = principal.user
    if user is None:
        raise HTTPException(403, "Not applicable")
    if user.email_verified:
        return {"ok": True, "note": "Already verified"}
    send_verification_email(db, user)
    return {"ok": True, "note": "Verification email sent"}


# ── TOTP enrolment ───────────────────────────────────────────────

@router.post("/mfa/setup")
def mfa_setup(principal: Principal = Depends(get_principal), db=Depends(get_db)):
    user = _human(principal)
    if user.mfa_enabled:
        raise HTTPException(409, "MFA is already enabled — disable it first to re-enrol")
    secret = security.new_totp_secret()
    user.mfa_secret_encrypted = encrypt_secrets({"totp": secret})
    db.commit()
    return {"secret": secret,
            "otpauth_uri": security.totp_provisioning_uri(secret, user.email)}


@router.post("/mfa/enable")
def mfa_enable(req: MfaEnableRequest, principal: Principal = Depends(get_principal),
               db=Depends(get_db)):
    user = _human(principal)
    secret = _totp_secret(user)
    if not secret:
        raise HTTPException(400, "Start with /mfa/setup")
    if not security.verify_totp(secret, req.code):
        raise HTTPException(400, "That code is not valid — check your authenticator app's clock")
    codes, hashes = security.new_recovery_codes()
    user.mfa_enabled = 1
    user.mfa_recovery_hashes = hashes
    db.commit()
    audit.record(db, action="auth.mfa.enabled", actor_email=user.email,
                 tenant_id=user.tenant_id)
    obs.event("auth.mfa.enabled", actor=user.email)
    return {"ok": True, "recovery_codes": codes,
            "note": "Store these recovery codes now — they are shown only once."}


@router.post("/mfa/disable")
def mfa_disable(req: MfaDisableRequest, principal: Principal = Depends(get_principal),
                db=Depends(get_db)):
    user = _human(principal)
    if not user.mfa_enabled:
        return {"ok": True}
    ok = (req.password and security.verify_password(req.password, user.password_hash)) or \
         (req.code and security.verify_totp(_totp_secret(user), req.code))
    if not ok:
        raise HTTPException(401, "Confirm with your password or a current code")
    if _requires_mfa(db.get(Tenant, user.tenant_id) if user.tenant_id else None):
        raise HTTPException(403, "Your workspace requires MFA — it cannot be disabled")
    user.mfa_enabled = 0
    user.mfa_secret_encrypted = ""
    user.mfa_recovery_hashes = []
    db.commit()
    audit.record(db, action="auth.mfa.disabled", actor_email=user.email,
                 tenant_id=user.tenant_id)
    obs.event("auth.mfa.disabled", actor=user.email, level="warn")
    return {"ok": True}


@router.post("/mfa/recovery-codes")
def mfa_regen_codes(principal: Principal = Depends(get_principal), db=Depends(get_db)):
    user = _human(principal)
    if not user.mfa_enabled:
        raise HTTPException(400, "MFA is not enabled")
    codes, hashes = security.new_recovery_codes()
    user.mfa_recovery_hashes = hashes
    db.commit()
    return {"recovery_codes": codes, "note": "Previous recovery codes are now invalid."}


# ── sessions (refresh tokens) ────────────────────────────────────

@router.get("/sessions")
def list_sessions(principal: Principal = Depends(get_principal),
                  x_refresh_token: str = Header(default=""),
                  kd_refresh: str | None = Cookie(default=None),
                  db=Depends(get_db)):
    user = _human(principal)
    this = ((x_refresh_token or kd_refresh or "").strip())
    this_hash = security.hash_refresh_token(this) if this else None
    now = dt.datetime.now(dt.timezone.utc)
    rows = (db.query(RefreshToken)
            .filter(RefreshToken.user_id == user.id, RefreshToken.revoked == 0)
            .order_by(RefreshToken.created_at.desc()).all())
    out = []
    for r in rows:
        exp = _aware(r.expires_at)
        if exp and exp < now:
            continue
        out.append({"id": r.id, "user_agent": r.user_agent, "ip": r.ip, "label": r.label,
                    "current": this_hash is not None and r.token_hash == this_hash,
                    "session_started_at": r.session_started_at.isoformat() if r.session_started_at else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None})
    return out


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: int, principal: Principal = Depends(get_principal), db=Depends(get_db)):
    user = _human(principal)
    row = db.get(RefreshToken, session_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, "Session not found")
    row.revoked = 1
    db.commit()
    audit.record(db, action="auth.session.revoked", actor_email=user.email,
                 tenant_id=user.tenant_id, detail=f"session #{session_id}")
    return {"revoked": session_id}


@router.delete("/sessions")
def revoke_all_sessions(principal: Principal = Depends(get_principal),
                        keep_current: bool = False,
                        x_refresh_token: str = Header(default=""),
                        kd_refresh: str | None = Cookie(default=None),
                        db=Depends(get_db)):
    user = _human(principal)
    q = db.query(RefreshToken).filter(RefreshToken.user_id == user.id,
                                      RefreshToken.revoked == 0)
    this = (x_refresh_token or kd_refresh or "").strip()
    if keep_current and this:
        q = q.filter(RefreshToken.token_hash != security.hash_refresh_token(this))
    n = q.update({"revoked": 1})
    db.commit()
    audit.record(db, action="auth.session.revoked_all", actor_email=user.email,
                 tenant_id=user.tenant_id,
                 detail=f"{n} sessions{' (kept current)' if keep_current else ''}")
    return {"revoked": n,
            "note": "Other sessions ended." if keep_current else "All sessions ended — sign in again."}


# ── shared internals ────────────────────────────────────────────

def _human(principal: Principal) -> User:
    if principal.user is None:
        raise HTTPException(403, "Not available for API keys")
    return principal.user


def _requires_mfa(tenant: Tenant | None) -> bool:
    return bool(tenant and (tenant.settings_json or {}).get("mfa_required"))


def _requires_verified(tenant: Tenant | None) -> bool:
    return bool(tenant and (tenant.settings_json or {}).get("require_verified_email"))


def _consume_token(db, raw: str, purpose: str) -> AuthToken:
    row = (db.query(AuthToken)
           .filter(AuthToken.token_hash == security.hash_email_token(raw),
                   AuthToken.purpose == purpose).first())
    if not row or row.used_at:
        raise HTTPException(400, "This link is invalid or has already been used")
    exp = row.expires_at.replace(tzinfo=dt.timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
    if exp < dt.datetime.now(dt.timezone.utc):
        raise HTTPException(400, "This link has expired — request a new one")
    row.used_at = utcnow()
    db.commit()
    return row


def send_verification_email(db, user: User) -> None:
    raw, h = security.new_email_token()
    db.add(AuthToken(user_id=user.id, purpose="verify_email", token_hash=h,
                     expires_at=utcnow() + dt.timedelta(days=3)))
    db.commit()
    authn.send_email(user.email, "Verify your KnowledgeDesk email",
                     f"Confirm your email address:\n{authn.link('/verify-email?token=' + raw)}")
