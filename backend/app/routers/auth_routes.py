"""Authentication endpoints: login, token refresh, logout, profile."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import security
from ..auth import Principal, get_db, get_principal
from ..config import get_settings
from ..database import RefreshToken, Tenant, User, utcnow
from ..services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

GENERIC_LOGIN_ERROR = "Incorrect email or password"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(max_length=200)


def _token_pair(db, user: User) -> dict:
    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
    access = security.create_access_token(
        user_id=user.id, email=user.email, role=user.role,
        tenant_id=user.tenant_id, tenant_slug=tenant.slug if tenant else None,
        password_version=user.password_version)
    raw_refresh, token_hash = security.new_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=token_hash,
                        expires_at=security.refresh_expiry()))
    db.commit()
    return {
        "access_token": access,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": get_settings().access_token_minutes * 60,
        "user": _user_out(user, tenant),
    }


def _user_out(user: User, tenant: Tenant | None) -> dict:
    return {
        "id": user.id, "email": user.email, "full_name": user.full_name,
        "role": user.role,
        "tenant": ({"slug": tenant.slug, "name": tenant.name}
                   if tenant else None),
        "force_password_change": bool(user.force_password_change),
    }


@router.post("/login")
def login(req: LoginRequest, db=Depends(get_db)):
    s = get_settings()
    email = req.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    # Same error for unknown email and wrong password — no account enumeration.
    if not user or not user.is_active:
        audit.record(db, action="auth.login.failed", actor_email=email,
                     detail="unknown or disabled account")
        raise HTTPException(401, GENERIC_LOGIN_ERROR)

    remaining = security.lockout_remaining_minutes(user.locked_until)
    if remaining:
        raise HTTPException(
            423, f"Account locked after repeated failures — try again in "
                 f"{remaining} min")

    if not security.verify_password(req.password, user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= s.login_max_failures:
            user.locked_until = (dt.datetime.now(dt.timezone.utc)
                                 + dt.timedelta(minutes=s.login_lockout_minutes))
            user.failed_logins = 0
        db.commit()
        audit.record(db, action="auth.login.failed", actor_email=email,
                     tenant_id=user.tenant_id, detail="wrong password")
        raise HTTPException(401, GENERIC_LOGIN_ERROR)

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    db.commit()
    audit.record(db, action="auth.login", actor_email=user.email,
                 actor_role=user.role, tenant_id=user.tenant_id)
    return _token_pair(db, user)


@router.post("/refresh")
def refresh(req: RefreshRequest, db=Depends(get_db)):
    token_hash = security.hash_refresh_token(req.refresh_token.strip())
    row = (db.query(RefreshToken)
           .filter(RefreshToken.token_hash == token_hash).first())
    if not row:
        raise HTTPException(401, "Invalid refresh token")

    if row.revoked:
        # Reuse of a rotated token = likely theft → revoke the whole family.
        db.query(RefreshToken).filter(
            RefreshToken.user_id == row.user_id).update({"revoked": 1})
        db.commit()
        audit.record(db, action="auth.refresh.reuse_detected",
                     detail=f"user_id={row.user_id} — all sessions revoked")
        raise HTTPException(401, "Session revoked — please sign in again")

    expires = row.expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.timezone.utc)
    if not expires or expires < dt.datetime.now(dt.timezone.utc):
        raise HTTPException(401, "Refresh token expired — please sign in again")

    user = db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Account is disabled")

    row.revoked = 1                                       # single-use rotation
    db.commit()
    return _token_pair(db, user)


@router.post("/logout")
def logout(req: RefreshRequest, principal: Principal = Depends(get_principal),
           db=Depends(get_db)):
    token_hash = security.hash_refresh_token(req.refresh_token.strip())
    db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash).update({"revoked": 1})
    db.commit()
    audit.record(db, action="auth.logout", actor_email=principal.email,
                 actor_role=principal.role,
                 tenant_id=principal.tenant.id if principal.tenant else None)
    return {"ok": True}


@router.get("/me")
def me(principal: Principal = Depends(get_principal)):
    if principal.user is None:
        return {"id": None, "email": "api-key", "role": "service",
                "tenant": {"slug": principal.tenant.slug,
                           "name": principal.tenant.name},
                "force_password_change": False}
    return _user_out(principal.user, principal.tenant)


@router.post("/change-password")
def change_password(req: ChangePasswordRequest,
                    principal: Principal = Depends(get_principal),
                    db=Depends(get_db)):
    user = principal.user
    if user is None:
        raise HTTPException(403, "API keys have no password")
    if not security.verify_password(req.current_password, user.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    problem = security.validate_password_policy(req.new_password, user.email)
    if problem:
        raise HTTPException(400, problem)
    user.password_hash = security.hash_password(req.new_password)
    user.password_version += 1                # invalidates every issued JWT
    user.force_password_change = 0
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id).update({"revoked": 1})
    db.commit()
    audit.record(db, action="auth.password_changed", actor_email=user.email,
                 actor_role=user.role, tenant_id=user.tenant_id)
    return {"ok": True, "note": "All sessions signed out — log in again"}
