"""Session lifetime hardening: rotation continuity, idle timeout, absolute cap,
concurrent-session limit, current-session marker, revoke-others."""
from __future__ import annotations

import datetime as dt

from app import security
from app.database import RefreshToken, SessionLocal

PW = "Passw0rd!123"


def _login(client, email, password=PW):
    return client.post("/api/auth/login", json={"email": email, "password": password}).json()


def _row(raw):
    db = SessionLocal()
    try:
        return db.query(RefreshToken).filter(
            RefreshToken.token_hash == security.hash_refresh_token(raw)).first()
    finally:
        db.close()


def _backdate(raw, *, started=None, last_used=None):
    db = SessionLocal()
    try:
        r = db.query(RefreshToken).filter(
            RefreshToken.token_hash == security.hash_refresh_token(raw)).first()
        if started is not None:
            r.session_started_at = started
        if last_used is not None:
            r.last_used_at = last_used
            r.created_at = last_used
        db.commit()
    finally:
        db.close()


# ── rotation continuity ─────────────────────────────────────────

def test_rotation_preserves_session_start(client, make_world):
    w = make_world()
    p = _login(client, f"alice@{w['slug']}.test")
    origin = _row(p["refresh_token"]).session_started_at

    p2 = client.post("/api/auth/refresh", json={"refresh_token": p["refresh_token"]}).json()
    assert _row(p2["refresh_token"]).session_started_at == origin
    # old token is now single-use-revoked
    assert client.post("/api/auth/refresh", json={"refresh_token": p["refresh_token"]}).status_code == 401


# ── idle timeout ────────────────────────────────────────────────

def test_idle_timeout_ends_the_session(client, make_world):
    w = make_world()
    p = _login(client, f"alice@{w['slug']}.test")
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=100)   # > 72h default
    _backdate(p["refresh_token"], last_used=old)

    r = client.post("/api/auth/refresh", json={"refresh_token": p["refresh_token"]})
    assert r.status_code == 401 and "inactiv" in r.json()["detail"].lower()


# ── absolute cap ────────────────────────────────────────────────

def test_absolute_lifetime_cap(client, make_world):
    w = make_world()
    p = _login(client, f"bob@{w['slug']}.test")
    # active recently, but the chain is older than AUTH_SESSION_MAX_DAYS (30)
    _backdate(p["refresh_token"],
              started=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=40),
              last_used=dt.datetime.now(dt.timezone.utc))
    r = client.post("/api/auth/refresh", json={"refresh_token": p["refresh_token"]})
    assert r.status_code == 401 and "expired" in r.json()["detail"].lower()


# ── concurrent-session cap ─────────────────────────────────────

def test_concurrent_session_cap_evicts_oldest(client, make_world):
    w = make_world()
    email = f"bob@{w['slug']}.test"
    pairs = [_login(client, email) for _ in range(6)]            # cap = 4 (conftest)
    hdr = {"Authorization": f"Bearer {pairs[-1]['access_token']}"}

    assert len(client.get("/api/auth/sessions", headers=hdr).json()) == 4
    # the two oldest chains were revoked (check the DB — hitting /refresh with a
    # revoked token would trip reuse-detection and nuke the whole family)
    for stale in pairs[:2]:
        assert _row(stale["refresh_token"]).revoked == 1
    for keep in pairs[2:]:
        assert _row(keep["refresh_token"]).revoked == 0
    # the newest still refreshes
    assert client.post("/api/auth/refresh",
                       json={"refresh_token": pairs[-1]["refresh_token"]}).status_code == 200


# ── current-session marker + revoke-others ────────────────────

def test_current_marker_and_revoke_others(client, make_world):
    w = make_world()
    email = f"alice@{w['slug']}.test"
    a = _login(client, email)
    b = _login(client, email)
    hdr = {"Authorization": f"Bearer {b['access_token']}", "X-Refresh-Token": b["refresh_token"]}

    rows = client.get("/api/auth/sessions", headers=hdr).json()
    assert len([r for r in rows if r["current"]]) == 1

    client.request("DELETE", "/api/auth/sessions?keep_current=true", headers=hdr)
    # b still refreshable, a is gone
    assert client.post("/api/auth/refresh", json={"refresh_token": b["refresh_token"]}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": a["refresh_token"]}).status_code == 401
