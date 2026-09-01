"""TOTP MFA, session management, API-key v2, login rate-limiting,
forgot/reset password, email verification, password history, SSO gating."""
from __future__ import annotations

import re

import pyotp
import pytest

from app import authn
from app.database import SessionLocal, Tenant, User
from app.routers import auth_routes

PW = "Passw0rd!123"          # conftest default for alice/bob/admin


def _login(client, email, password=PW):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ── TOTP MFA ─────────────────────────────────────────────────────

def test_totp_enrol_challenge_and_login(client, make_world):
    w = make_world()
    setup = client.post("/api/auth/mfa/setup", headers=w["alice"]).json()
    secret = setup["secret"]
    assert setup["otpauth_uri"].startswith("otpauth://totp/")

    enabled = client.post("/api/auth/mfa/enable", headers=w["alice"],
                          json={"code": pyotp.TOTP(secret).now()}).json()
    assert enabled["ok"] and len(enabled["recovery_codes"]) == 10

    # password alone no longer yields a session
    r = _login(client, f"alice@{w['slug']}.test")
    assert r.status_code == 200 and r.json().get("mfa_required") is True
    mfa_token = r.json()["mfa_token"]

    bad = client.post("/api/auth/login/mfa", json={"mfa_token": mfa_token, "code": "000000"})
    assert bad.status_code == 401
    good = client.post("/api/auth/login/mfa",
                       json={"mfa_token": mfa_token, "code": pyotp.TOTP(secret).now()})
    assert good.status_code == 200 and good.json()["access_token"]


def test_recovery_code_is_single_use(client, make_world):
    w = make_world()
    secret = client.post("/api/auth/mfa/setup", headers=w["alice"]).json()["secret"]
    codes = client.post("/api/auth/mfa/enable", headers=w["alice"],
                        json={"code": pyotp.TOTP(secret).now()}).json()["recovery_codes"]

    tok = _login(client, f"alice@{w['slug']}.test").json()["mfa_token"]
    assert client.post("/api/auth/login/mfa", json={"mfa_token": tok, "code": codes[0]}).status_code == 200
    tok2 = _login(client, f"alice@{w['slug']}.test").json()["mfa_token"]
    assert client.post("/api/auth/login/mfa", json={"mfa_token": tok2, "code": codes[0]}).status_code == 401


def test_mfa_required_policy_blocks_disable(client, make_world):
    w = make_world()
    secret = client.post("/api/auth/mfa/setup", headers=w["admin"]).json()["secret"]
    client.post("/api/auth/mfa/enable", headers=w["admin"], json={"code": pyotp.TOTP(secret).now()})
    client.put("/api/access/auth-policy", headers=w["admin"], json={"mfa_required": True})
    r = client.post("/api/auth/mfa/disable", headers=w["admin"], json={"password": PW})
    assert r.status_code == 403


# ── sessions ─────────────────────────────────────────────────────

def test_sessions_list_and_revoke(client, make_world):
    w = make_world()
    email = f"bob@{w['slug']}.test"
    _login(client, email); _login(client, email)
    hdr = {"Authorization": f"Bearer {_login(client, email).json()['access_token']}"}

    sessions = client.get("/api/auth/sessions", headers=hdr).json()
    assert len(sessions) >= 3
    assert client.delete(f"/api/auth/sessions/{sessions[0]['id']}", headers=hdr).status_code == 200
    assert len(client.get("/api/auth/sessions", headers=hdr).json()) == len(sessions) - 1

    r = client.delete("/api/auth/sessions", headers=hdr)
    assert r.status_code == 200 and r.json()["revoked"] >= 1
    assert client.get("/api/auth/sessions", headers=hdr).json() == []


# ── API keys v2 ──────────────────────────────────────────────────

def test_api_key_lifecycle(client, make_world):
    w = make_world()
    created = client.post("/api/access/api-keys", headers=w["admin"],
                          json={"name": "ci"}).json()
    raw = created["api_key"]
    assert raw.startswith("kd_")

    kh = {"X-API-Key": raw}
    assert client.get("/api/documents", headers=kh).status_code == 200
    # can manage connectors (service role) but not users
    assert client.get("/api/users", headers=kh).status_code == 403

    assert client.delete(f"/api/access/api-keys/{created['id']}", headers=w["admin"]).status_code == 200
    assert client.get("/api/documents", headers=kh).status_code == 401
    # legacy plaintext tenant key still works
    assert client.get("/api/documents", headers=w["service"]).status_code == 200


def test_expired_api_key_rejected(client, make_world):
    w = make_world()
    created = client.post("/api/access/api-keys", headers=w["admin"],
                          json={"name": "short", "expires_in_days": -1}).json()
    assert client.get("/api/documents", headers={"X-API-Key": created["api_key"]}).status_code == 401


# ── login rate limiting ─────────────────────────────────────────

def test_login_rate_limited(client):
    email = "ratelimit-target@nowhere.test"
    codes = [_login(client, email, "wrong").status_code for _ in range(7)]
    assert 429 in codes                     # AUTH_LOGIN_RATE_PER_MIN=5 in conftest
    assert codes.index(429) >= 5


# ── password reset + history ────────────────────────────────────

def test_forgot_and_reset_password(client, make_world, monkeypatch):
    w = make_world()
    sent = {}
    monkeypatch.setattr(authn, "send_email", lambda to, s, b: sent.update(to=to, body=b))

    email = f"alice@{w['slug']}.test"
    assert client.post("/api/auth/password/forgot", json={"email": email}).status_code == 200
    token = re.search(r"token=([\w\-]+)", sent["body"]).group(1)

    new_pw = "Rotated!99887"
    assert client.post("/api/auth/password/reset",
                       json={"token": token, "new_password": new_pw}).status_code == 200
    assert client.post("/api/auth/password/reset",
                       json={"token": token, "new_password": new_pw}).status_code == 400  # single use

    assert _login(client, email, new_pw).status_code == 200
    assert _login(client, email, PW).status_code == 401


def test_password_history_blocks_reuse(client, make_world):
    w = make_world()
    hdr = w["alice"]
    r1 = client.post("/api/auth/change-password", headers=hdr,
                     json={"current_password": PW, "new_password": "FirstNew!123"})
    assert r1.status_code == 200
    # need a fresh token — old sessions were revoked
    email = f"alice@{w['slug']}.test"
    hdr = {"Authorization": f"Bearer {_login(client, email, 'FirstNew!123').json()['access_token']}"}
    r2 = client.post("/api/auth/change-password", headers=hdr,
                     json={"current_password": "FirstNew!123", "new_password": PW})
    assert r2.status_code == 400 and "last" in r2.json()["detail"]


# ── email verification ─────────────────────────────────────────

def test_verified_email_required(client, make_world, monkeypatch):
    w = make_world()
    sent = {}
    monkeypatch.setattr(authn, "send_email", lambda to, s, b: sent.update(body=b))

    db = SessionLocal()
    try:
        u = db.get(User, w["ids"]["bob"])
        u.email_verified = 0
        t = db.get(Tenant, w["tenant_id"])
        t.settings_json = {**(t.settings_json or {}), "require_verified_email": True}
        db.commit()
        auth_routes.send_verification_email(db, u)
    finally:
        db.close()

    email = f"bob@{w['slug']}.test"
    assert _login(client, email).status_code == 403
    token = re.search(r"token=([\w\-]+)", sent["body"]).group(1)
    assert client.post("/api/auth/email/verify", json={"token": token}).status_code == 200
    assert _login(client, email).status_code == 200


# ── SSO entitlement gating ────────────────────────────────────

def test_sso_config_requires_entitlement(client, make_world):
    w = make_world()
    body = {"issuer": "https://idp.example.com", "client_id": "abc", "client_secret": "shh",
            "allowed_domains": [], "is_active": True}
    assert client.put("/api/access/sso", headers=w["admin"], json=body).status_code == 402

    db = SessionLocal()
    try:
        t = db.get(Tenant, w["tenant_id"])
        t.settings_json = {**(t.settings_json or {}), "entitlements": ["sso"]}
        db.commit()
    finally:
        db.close()

    assert client.put("/api/access/sso", headers=w["admin"], json=body).status_code == 200
    look = client.get(f"/api/auth/sso/lookup?workspace={w['slug']}").json()
    assert look["available"] is True and look["entitled"] is True


def test_public_base_url_drives_sso_redirect_and_links(monkeypatch):
    from app.config import get_settings
    from app.routers.sso import _callback_uri
    from app import authn

    s = get_settings()
    monkeypatch.setattr(s, "public_base_url", "https://kd.example.com")
    assert s.app_base_url == "https://kd.example.com"
    assert _callback_uri(None) == "https://kd.example.com/api/auth/sso/callback"
    assert authn.link("/verify-email?token=x") == "https://kd.example.com/verify-email?token=x"


def test_sso_start_redirects_to_idp(client, make_world, monkeypatch):
    w = make_world()
    db = SessionLocal()
    try:
        t = db.get(Tenant, w["tenant_id"])
        t.settings_json = {**(t.settings_json or {}), "entitlements": ["sso"]}
        db.commit()
    finally:
        db.close()
    client.put("/api/access/sso", headers=w["admin"], json={
        "issuer": "https://idp.example.com", "client_id": "abc", "client_secret": "shh",
        "allowed_domains": [], "is_active": True})

    monkeypatch.setattr(authn, "oidc_discover", lambda issuer: {
        "authorization_endpoint": "https://idp.example.com/authorize",
        "token_endpoint": "https://idp.example.com/token", "jwks_uri": "https://idp.example.com/jwks",
    })
    r = client.get(f"/api/auth/sso/start?workspace={w['slug']}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith("https://idp.example.com/authorize?")
    assert "code_challenge=" in r.headers["location"]
