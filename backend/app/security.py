"""Security primitives: password hashing, JWT access tokens, refresh tokens.

Design notes (enterprise posture, not POC):
* Passwords:      bcrypt with per-password salt. No plaintext anywhere, ever.
* Access tokens:  HS256 JWT, short-lived (default 30 min). Claims carry the
                  user id, role and tenant so every request is authorised
                  server-side from the token — never from the request body.
                  A `pwv` (password version) claim invalidates all of a
                  user's outstanding tokens the moment their password changes.
* Refresh tokens: opaque 256-bit values. Only their SHA-256 hash is stored.
                  Single-use rotation: each refresh issues a new token and
                  revokes the old one. If a *revoked* token is ever presented
                  again (theft indicator), the entire family for that user is
                  revoked and they must log in again.
* JWT secret:     taken from env if set; otherwise generated once and
                  persisted under DATA_DIR so restarts don't log everyone out
                  and we never ship a hard-coded secret.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from pathlib import Path

import bcrypt
import jwt

from .config import get_settings

ACCESS_TOKEN_TYPE = "access"

# ── JWT secret management ───────────────────────────────────────────

_secret_cache: str | None = None


def jwt_secret() -> str:
    global _secret_cache
    if _secret_cache:
        return _secret_cache
    s = get_settings()
    if s.jwt_secret:
        _secret_cache = s.jwt_secret
        return _secret_cache
    path = Path(s.data_dir) / ".jwt_secret"
    if path.exists():
        _secret_cache = path.read_text().strip()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        _secret_cache = secrets.token_urlsafe(48)
        path.write_text(_secret_cache)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return _secret_cache


# ── Passwords ───────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def validate_password_policy(plain: str, email: str = "") -> str | None:
    """Return an error message, or None if the password is acceptable."""
    s = get_settings()
    if len(plain) < s.password_min_length:
        return f"Password must be at least {s.password_min_length} characters"
    if email and plain.lower() == email.lower():
        return "Password must not be the same as the email address"
    return None


# ── Access tokens (JWT) ─────────────────────────────────────────────

def create_access_token(*, user_id: int, email: str, role: str,
                        tenant_id: int | None, tenant_slug: str | None,
                        password_version: int) -> str:
    s = get_settings()
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "tid": tenant_id,
        "ten": tenant_slug,
        "pwv": password_version,
        "type": ACCESS_TOKEN_TYPE,
        "jti": secrets.token_hex(8),
        "iat": now,
        "exp": now + dt.timedelta(minutes=s.access_token_minutes),
    }
    return jwt.encode(payload, jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> dict | None:
    """Strictly verify signature, expiry and token type. None on any failure."""
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=["HS256"],
                             options={"require": ["exp", "sub", "type"]})
    except jwt.PyJWTError:
        return None
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        return None
    return payload


# ── Refresh tokens (opaque, hashed at rest) ─────────────────────────

def new_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash). Only the hash is ever stored."""
    raw = "kdr_" + secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def refresh_expiry() -> dt.datetime:
    return (dt.datetime.now(dt.timezone.utc)
            + dt.timedelta(days=get_settings().refresh_token_days))


# ── Account lockout ─────────────────────────────────────────────────

def lockout_remaining_minutes(locked_until: dt.datetime | None) -> int:
    if not locked_until:
        return 0
    now = dt.datetime.now(dt.timezone.utc)
    if locked_until.tzinfo is None:                       # SQLite naive datetimes
        locked_until = locked_until.replace(tzinfo=dt.timezone.utc)
    delta = (locked_until - now).total_seconds()
    return max(0, int(delta // 60) + (1 if delta % 60 else 0))
