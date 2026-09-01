"""Authentication support services: login rate-limiting, transactional email,
subscription entitlements, and a small generic-OIDC client for SSO.

Kept separate from ``app.auth`` (which is the per-request authorization layer)
and ``app.security`` (crypto primitives).
"""
from __future__ import annotations

import logging
import smtplib
import threading
import time
from collections import defaultdict, deque
from email.message import EmailMessage

import httpx

from .config import get_settings

log = logging.getLogger("knowledgedesk.authn")


# ── login rate limiting (in-process sliding window) ────────────────

class _SlidingWindow:
    def __init__(self):
        self._events: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int = 60) -> bool:
        """Record an attempt; return True if it is *within* the limit."""
        now = time.time()
        with self._lock:
            q = self._events[key]
            while q and q[0] < now - window:
                q.popleft()
            q.append(now)
            if len(q) > 5000:                      # pathological guard
                q.clear()
            return len(q) <= limit

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


login_limiter = _SlidingWindow()


def check_login_rate(ip: str, email: str) -> str | None:
    """Return an error string if this attempt should be throttled, else None."""
    s = get_settings()
    ok_ip = login_limiter.hit(f"ip:{ip}", s.auth_login_rate_ip_per_min)
    ok_pair = login_limiter.hit(f"pair:{ip}:{email.lower()}", s.auth_login_rate_per_min)
    if not (ok_ip and ok_pair):
        return "Too many sign-in attempts — wait a minute and try again"
    return None


def clear_login_rate(ip: str, email: str) -> None:
    login_limiter.reset(f"pair:{ip}:{email.lower()}")


# ── transactional email (pluggable) ───────────────────────────────

def send_email(to: str, subject: str, body: str) -> None:
    """Deliver a plaintext email via the configured sender. Never raises."""
    s = get_settings()
    mode = (s.email_sender or "console").lower()
    try:
        if mode == "noop":
            return
        if mode == "console":
            log.info("EMAIL → %s | %s\n%s", to, subject, body)
            return
        if mode == "smtp":
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = s.email_from, to, subject
            msg.set_content(body)
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as srv:
                if s.smtp_starttls:
                    srv.starttls()
                if s.smtp_user:
                    srv.login(s.smtp_user, s.smtp_password)
                srv.send_message(msg)
            return
        log.warning("unknown EMAIL_SENDER=%s — email dropped", mode)
    except Exception as exc:                       # delivery must not break the flow
        log.warning("email send failed (%s): %s", mode, exc)


def link(path: str) -> str:
    return f"{get_settings().email_public_base_url.rstrip('/')}{path}"


# ── subscription entitlements ─────────────────────────────────────

KNOWN_ENTITLEMENTS = {"sso"}


def _global_entitlements() -> set[str]:
    raw = (get_settings().entitlements or "").strip()
    if raw == "*":
        return set(KNOWN_ENTITLEMENTS)
    return {p.strip() for p in raw.split(",") if p.strip()}


def entitlement_enabled(tenant, name: str) -> bool:
    if name in _global_entitlements():
        return True
    if tenant is not None:
        ents = (tenant.settings_json or {}).get("entitlements") or []
        if isinstance(ents, list) and (name in ents or "*" in ents):
            return True
    return False


def tenant_entitlements(tenant) -> dict[str, bool]:
    return {e: entitlement_enabled(tenant, e) for e in sorted(KNOWN_ENTITLEMENTS)}


# ── generic OIDC client ──────────────────────────────────────────

_disco_cache: dict[str, tuple[float, dict]] = {}


def oidc_discover(issuer: str) -> dict:
    issuer = issuer.rstrip("/")
    now = time.time()
    hit = _disco_cache.get(issuer)
    if hit and now - hit[0] < 3600:
        return hit[1]
    url = issuer + "/.well-known/openid-configuration"
    r = httpx.get(url, timeout=8)
    r.raise_for_status()
    doc = r.json()
    _disco_cache[issuer] = (now, doc)
    return doc


def oidc_authorize_url(conf: dict, client_id: str, redirect_uri: str,
                       state: str, code_challenge: str) -> str:
    from urllib.parse import urlencode
    params = {
        "response_type": "code", "client_id": client_id,
        "redirect_uri": redirect_uri, "scope": "openid email profile",
        "state": state, "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return conf["authorization_endpoint"] + "?" + urlencode(params)


def oidc_exchange_code(conf: dict, client_id: str, client_secret: str,
                       code: str, redirect_uri: str, code_verifier: str) -> dict:
    r = httpx.post(conf["token_endpoint"], timeout=10, data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": redirect_uri, "client_id": client_id,
        "client_secret": client_secret, "code_verifier": code_verifier,
    })
    r.raise_for_status()
    return r.json()


def oidc_verify_id_token(conf: dict, id_token: str, client_id: str, issuer: str) -> dict:
    import jwt
    from jwt import PyJWKClient
    jwks = PyJWKClient(conf["jwks_uri"])
    key = jwks.get_signing_key_from_jwt(id_token).key
    return jwt.decode(id_token, key, algorithms=conf.get("id_token_signing_alg_values_supported", ["RS256"]),
                      audience=client_id, issuer=issuer.rstrip("/"),
                      options={"require": ["exp", "iat", "sub"]})
