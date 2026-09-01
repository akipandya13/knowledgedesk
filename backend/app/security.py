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
import logging
import secrets
import string
from pathlib import Path

import bcrypt
import httpx
import jwt
import pyotp

from .config import get_settings

log = logging.getLogger("knowledgedesk.security")

ACCESS_TOKEN_TYPE = "access"
MFA_TOKEN_TYPE = "mfa"                # interim token issued between password and TOTP

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


def validate_password_policy(plain: str, email: str = "",
                             history_hashes: list[str] | None = None) -> str | None:
    """Return an error message, or None if the password is acceptable.

    Enforces length + configurable character-class requirements, forbids reuse of
    the last N passwords, and (opt-in) rejects passwords in the Have I Been Pwned
    breach corpus via the keyless k-anonymity range API.
    """
    s = get_settings()
    if len(plain) < s.password_min_length:
        return f"Password must be at least {s.password_min_length} characters"
    if email and plain.lower() == email.lower():
        return "Password must not be the same as the email address"
    if s.auth_pw_require_upper and not any(c.isupper() for c in plain):
        return "Password must contain an uppercase letter"
    if s.auth_pw_require_lower and not any(c.islower() for c in plain):
        return "Password must contain a lowercase letter"
    if s.auth_pw_require_digit and not any(c.isdigit() for c in plain):
        return "Password must contain a digit"
    if s.auth_pw_require_symbol and not any(c in string.punctuation for c in plain):
        return "Password must contain a symbol"
    for h in (history_hashes or []):
        if verify_password(plain, h):
            return f"Password must not match any of your last {s.auth_pw_history} passwords"
    if s.auth_pw_breach_check and password_is_breached(plain):
        return "This password has appeared in a known data breach — choose another"
    return None


def password_is_breached(plain: str) -> bool:
    """HIBP range API (k-anonymity): only the first 5 SHA-1 chars leave the host."""
    digest = hashlib.sha1(plain.encode()).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        r = httpx.get(f"https://api.pwnedpasswords.com/range/{prefix}",
                      headers={"Add-Padding": "true"}, timeout=4)
        r.raise_for_status()
        return any(line.split(":")[0] == suffix for line in r.text.splitlines())
    except Exception as exc:                       # network/DNS/etc — fail open
        log.warning("HIBP breach check unavailable: %s", exc)
        return False


# ── TOTP (multi-factor) ────────────────────────────────────────────

def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=email, issuer_name=get_settings().auth_totp_issuer)


def verify_totp(secret: str, code: str) -> bool:
    if not (secret and code):
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)
    except Exception:
        return False


def new_recovery_codes(n: int = 10) -> tuple[list[str], list[str]]:
    """Return (plaintext_codes, sha256_hashes). Plaintext shown once only."""
    codes = ["-".join(
        "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
        for _ in range(3)) for _ in range(n)]
    return codes, [hashlib.sha256(c.encode()).hexdigest() for c in codes]


def recovery_code_hash(raw: str) -> str:
    return hashlib.sha256(raw.strip().lower().encode()).hexdigest()


def create_mfa_token(user_id: int) -> str:
    """Short-lived token proving password succeeded; exchanged for a session
    after the TOTP step. Cannot be used as an access token."""
    s = get_settings()
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode({"sub": str(user_id), "type": MFA_TOKEN_TYPE, "iat": now,
                       "exp": now + dt.timedelta(minutes=s.auth_mfa_token_minutes)},
                      jwt_secret(), algorithm="HS256")


def decode_mfa_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=["HS256"],
                             options={"require": ["exp", "sub", "type"]})
    except jwt.PyJWTError:
        return None
    return payload if payload.get("type") == MFA_TOKEN_TYPE else None


# ── Email tokens (verification / password reset) ───────────────────

def new_email_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_email_token(raw: str) -> str:
    return hashlib.sha256(raw.strip().encode()).hexdigest()


# ── API keys (hashed at rest) ──────────────────────────────────────

def new_api_key_pair() -> tuple[str, str, str]:
    """Return (raw_key, prefix, sha256_hash). Only prefix+hash are stored."""
    raw = "kd_" + secrets.token_urlsafe(30)
    return raw, raw[:12], hashlib.sha256(raw.encode()).hexdigest()


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.strip().encode()).hexdigest()


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
