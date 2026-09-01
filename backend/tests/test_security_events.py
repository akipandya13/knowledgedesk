"""Security event logging: authorization denials, rejected credentials,
and password-expiry enforcement."""
from __future__ import annotations

import datetime as dt

from app import observability as obs
from app.database import SessionLocal, User

PW = "Passw0rd!123"


def _metric_names():
    return {m["name"] for m in obs.snapshot()["metrics"]}


# ── authorization denials ──────────────────────────────────────

def test_authz_denied_emits_security_event(client, make_world):
    w = make_world()
    # member reaching an admin surface
    assert client.get("/api/admin/audit", headers=w["alice"]).status_code == 403
    obs.flush()

    r = client.get("/api/observability/events?kind=authz.denied", headers=w["superadmin"])
    assert r.status_code == 200
    events = r.json()["events"]
    assert events, "expected an authz.denied event"
    top = events[0]
    assert top["fields"]["permission"] == "audit.read"
    assert top["actor"] == f"alice@{w['slug']}.test"
    assert "authz.denied" in _metric_names()


def test_superadmin_workspace_denial_is_logged(client, make_world):
    w = make_world()
    assert client.get("/api/documents", headers=w["superadmin"]).status_code == 403
    obs.flush()
    kinds = [e["kind"] for e in
             client.get("/api/observability/events", headers=w["superadmin"]).json()["events"]]
    assert "authz.denied" in kinds


# ── rejected credentials ───────────────────────────────────────

def test_bad_token_emits_rejection_metric(client):
    assert client.get("/api/documents",
                      headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401
    assert client.get("/api/documents", headers={"X-API-Key": "nope"}).status_code == 401
    assert "auth.token.rejected" in _metric_names()


# ── password expiry (opt-in) ──────────────────────────────────

def test_password_expiry_forces_change_on_login(client, make_world, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "auth_pw_max_age_days", 30)
    w = make_world()

    db = SessionLocal()
    try:
        u = db.get(User, w["ids"]["bob"])
        u.password_changed_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=45)
        db.commit()
    finally:
        db.close()

    r = client.post("/api/auth/login",
                    json={"email": f"bob@{w['slug']}.test", "password": PW})
    assert r.status_code == 200
    assert r.json()["user"]["force_password_change"] is True

    obs.flush()
    kinds = [e["kind"] for e in
             client.get("/api/observability/events?kind=auth.password.expired",
                        headers=w["admin"]).json()["events"]]
    assert "auth.password.expired" in kinds


def test_password_expiry_off_by_default(client, make_world):
    w = make_world()
    db = SessionLocal()
    try:
        u = db.get(User, w["ids"]["alice"])
        u.password_changed_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=999)
        db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/login",
                    json={"email": f"alice@{w['slug']}.test", "password": PW})
    assert r.status_code == 200 and r.json()["user"]["force_password_change"] is False


# ── password policy is enforced (sanity) ──────────────────────

def test_password_policy_min_length_enforced(client, make_world):
    w = make_world()
    r = client.post("/api/auth/change-password", headers=w["alice"],
                    json={"current_password": PW, "new_password": "short"})
    assert r.status_code == 400 and "at least" in r.json()["detail"].lower()
