"""Governance: the tamper-evident audit trail and the user-activity stream.

Covers the hash chain + verification, the filtered/CSV read APIs, the request
firehose + semantic activity events, the self-service ``/api/me/activity`` view,
the ``activity.read`` gate and the retention purge script.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app.database import ActivityLog, AuditLog, SessionLocal
from app.services import audit as audit_svc


# ── helpers ────────────────────────────────────────────────────────

def _login(client, email, password="Passw0rd!123"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed_audited_actions(client, w):
    """A few security-relevant mutations so the chain has real rows."""
    client.post("/api/users", headers=w["admin"],
                json={"email": f"newbie@{w['slug']}.test", "password": "Passw0rd!123",
                      "full_name": "Newbie", "role": "member"})
    client.put("/api/admin/settings", headers=w["admin"], json={"settings": {}})


# ── hash chain ─────────────────────────────────────────────────────

def test_audit_chain_verifies_after_real_activity(client, make_world):
    w = make_world()
    _seed_audited_actions(client, w)
    r = client.get("/api/admin/audit/verify", headers=w["admin"])
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["checked"] >= 2
    assert body["first_broken"] is None


def test_audit_tampering_is_detected(client, make_world):
    w = make_world()
    _seed_audited_actions(client, w)

    db = SessionLocal()
    try:
        row = (db.query(AuditLog)
               .filter(AuditLog.tenant_id == w["tenant_id"])
               .order_by(AuditLog.seq.asc()).first())
        row.detail = (row.detail or "") + " (edited)"
        db.commit()
        broken_seq = row.seq
    finally:
        db.close()

    body = client.get("/api/admin/audit/verify", headers=w["admin"]).json()
    assert body["ok"] is False
    assert body["first_broken"]["seq"] == broken_seq


def test_audit_deletion_breaks_the_chain(client, make_world):
    w = make_world()
    _seed_audited_actions(client, w)
    _seed_audited_actions(client, w)

    db = SessionLocal()
    try:
        rows = (db.query(AuditLog).filter(AuditLog.tenant_id == w["tenant_id"])
                .order_by(AuditLog.seq.asc()).all())
        db.delete(rows[1])                       # snip a link out of the middle
        db.commit()
    finally:
        db.close()

    body = client.get("/api/admin/audit/verify", headers=w["admin"]).json()
    assert body["ok"] is False


# ── structured fields + filters ────────────────────────────────────

def test_audit_rows_carry_structured_target(client, make_world, monkeypatch):
    w = make_world()
    monkeypatch.setattr("app.routers.documents.vectorstore.delete_document",
                        lambda *a, **k: None)
    up = client.post("/api/documents/upload", headers=w["admin"],
                     files={"files": ("policy.txt", b"hello world", "text/plain")},
                     data={"scope": "company"})
    doc_id = up.json()["accepted"][0]["id"]
    client.delete(f"/api/documents/{doc_id}", headers=w["admin"])

    rows = client.get("/api/admin/audit?prefix=document.", headers=w["admin"]).json()
    actions = {r["action"]: r for r in rows}
    assert "document.uploaded" in actions and "document.deleted" in actions
    assert actions["document.deleted"]["target_type"] == "document"
    assert actions["document.deleted"]["target_id"] == str(doc_id)


def test_audit_filters_by_prefix_and_time(client, make_world):
    w = make_world()
    _seed_audited_actions(client, w)

    only_user = client.get("/api/admin/audit?prefix=user.", headers=w["admin"]).json()
    assert only_user and all(r["action"].startswith("user.") for r in only_user)

    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
    assert client.get("/api/admin/audit", params={"since": future},
                      headers=w["admin"]).json() == []


def test_audit_bad_timestamp_is_422(client, make_world):
    w = make_world()
    assert client.get("/api/admin/audit?since=not-a-date", headers=w["admin"]).status_code == 422


# ── CSV export ─────────────────────────────────────────────────────

def test_audit_csv_export_is_recorded_as_activity(client, make_world):
    w = make_world()
    _seed_audited_actions(client, w)

    r = client.get("/api/admin/audit?format=csv", headers=w["admin"])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0].startswith("id,seq,created_at")

    acts = client.get("/api/admin/activity?prefix=export.", headers=w["admin"]).json()
    assert any(a["action"] == "export.audit" for a in acts)
    # …and the export itself is in the tamper-evident log too
    aud = client.get("/api/admin/audit?prefix=audit.", headers=w["admin"]).json()
    assert any(a["action"] == "audit.exported" for a in aud)


# ── activity: request firehose ─────────────────────────────────────

def test_authenticated_request_is_recorded(client, make_world):
    w = make_world()
    client.get("/api/documents", headers=w["alice"])
    rows = client.get("/api/admin/activity", headers=w["admin"]).json()
    hit = [r for r in rows if r["action"] == "get:/api/documents"]
    assert hit and hit[0]["category"] == "read"
    assert hit[0]["actor"] == f"alice@{w['slug']}.test"


def test_health_and_anonymous_calls_are_not_recorded(client, make_world):
    w = make_world()
    client.get("/api/health")
    client.get("/api/documents")                 # 401, no principal
    before = client.get("/api/admin/activity", headers=w["admin"]).json()
    routes = {r["route"] for r in before}
    assert "/api/health" not in routes


# ── activity: permission gate ──────────────────────────────────────

def test_activity_read_requires_permission(client, make_world):
    w = make_world()
    assert client.get("/api/admin/activity", headers=w["alice"]).status_code == 403
    assert client.get("/api/admin/activity", headers=w["admin"]).status_code == 200
    # superadmin has no workspace-content access to this surface
    assert client.get("/api/admin/activity", headers=w["superadmin"]).status_code == 403


# ── activity: semantic events ──────────────────────────────────────

def test_login_records_session_start(client, make_world):
    w = make_world()
    hdr = _login(client, f"alice@{w['slug']}.test")
    mine = client.get("/api/me/activity?prefix=session.", headers=hdr).json()
    assert any(r["action"] == "session.start" for r in mine)


def test_document_retrieved_is_tracked(client, make_world, monkeypatch):
    w = make_world()
    monkeypatch.setattr("app.services.rag.embeddings.embed_query",
                        lambda *a, **k: [0.1, 0.2, 0.3])
    monkeypatch.setattr(
        "app.services.rag.vectorstore.search",
        lambda *a, **k: [{"doc_id": 42, "filename": "handbook.txt", "page": 1,
                          "text": "body", "score": 0.9, "scope": "tenant",
                          "embedding_model": "m"}])
    r = client.post("/api/query/search", headers=w["alice"],
                    json={"question": "what is the leave policy"})
    assert r.status_code == 200

    rows = client.get("/api/admin/activity?prefix=document.retrieved",
                      headers=w["admin"]).json()
    assert rows and rows[0]["target_id"] == "42"
    assert rows[0]["user_id"] == w["ids"]["alice"]


# ── /api/me/activity is self-scoped ───────────────────────────────

def test_me_activity_only_shows_own_rows(client, make_world):
    w = make_world()
    client.get("/api/documents", headers=w["alice"])
    client.get("/api/collections", headers=w["bob"])

    alice_hdr = _login(client, f"alice@{w['slug']}.test")
    rows = client.get("/api/me/activity", headers=alice_hdr).json()
    assert rows
    assert all(r["user_id"] == w["ids"]["alice"] for r in rows)
    assert all(r["actor"] == f"alice@{w['slug']}.test" for r in rows)


# ── retention purge ───────────────────────────────────────────────

def test_purge_logs_trims_old_activity_only(client, make_world):
    w = make_world()
    db = SessionLocal()
    try:
        old = ActivityLog(tenant_id=w["tenant_id"], user_id=w["ids"]["alice"],
                          actor_email="old@x", action="get:/api/documents",
                          category="read",
                          created_at=dt.datetime(2000, 1, 1))
        fresh = ActivityLog(tenant_id=w["tenant_id"], user_id=w["ids"]["alice"],
                            actor_email="new@x", action="get:/api/documents",
                            category="read")
        db.add_all([old, fresh])
        db.commit()
    finally:
        db.close()

    from scripts.purge_logs import main as purge
    assert purge(["--activity-days", "1", "--audit-days", "0", "--yes"]) == 0

    db = SessionLocal()
    try:
        remaining = {r.actor_email for r in db.query(ActivityLog)
                     .filter(ActivityLog.tenant_id == w["tenant_id"]).all()}
        assert "old@x" not in remaining
        assert "new@x" in remaining
    finally:
        db.close()


# ── data-modification history (before → after) ────────────────────

def test_diff_helper_redacts_secret_fields():
    d = audit_svc.diff(
        {"name": "old", "api_key": "SECRET1", "port": 5432},
        {"name": "new", "api_key": "SECRET2", "port": 5432})
    assert d["name"] == ["old", "new"]
    assert d["api_key"] == ["***", "***"]        # changed, but value masked
    assert "port" not in d                       # unchanged
    assert "SECRET" not in repr(d)


def test_user_update_records_before_after(client, make_world):
    w = make_world()
    r = client.patch(f"/api/users/{w['ids']['alice']}", headers=w["admin"],
                     json={"role": "tenant_admin"})
    assert r.status_code == 200

    rows = client.get("/api/admin/audit?prefix=user.updated", headers=w["admin"]).json()
    assert rows
    row = rows[0]
    assert row["target_type"] == "user" and row["target_id"] == str(w["ids"]["alice"])
    assert row["changes"]["role"] == ["member", "tenant_admin"]


def test_settings_change_records_a_diff(client, make_world):
    w = make_world()
    client.put("/api/admin/settings", headers=w["admin"],
               json={"settings": {"model_profile": "demo_fast", "retrieval_top_k": 9}})
    row = client.get("/api/admin/audit?prefix=tenant.model_settings_changed",
                     headers=w["admin"]).json()[0]
    assert row["changes"]["retrieval_top_k"] == [None, 9]
    assert row["target_type"] == "workspace_settings"


def test_audit_history_endpoint_returns_entity_timeline(client, make_world):
    w = make_world()
    # create through the API so the timeline has a `user.created` entry too
    uid = client.post("/api/users", headers=w["admin"],
                      json={"email": f"carol@{w['slug']}.test", "password": "Passw0rd!123",
                            "full_name": "Carol", "role": "member"}).json()["id"]
    client.patch(f"/api/users/{uid}", headers=w["admin"], json={"full_name": "Carol One"})
    client.patch(f"/api/users/{uid}", headers=w["admin"], json={"clearance": 20})

    hist = client.get(
        f"/api/admin/audit/history?target_type=user&target_id={uid}",
        headers=w["admin"]).json()
    assert len(hist) >= 3                        # created + 2 updates
    assert hist[0]["created_at"] >= hist[-1]["created_at"]   # newest first
    assert {h["action"] for h in hist} >= {"user.created", "user.updated"}
    assert any(h["action"] == "user.updated" and "clearance" in (h["changes"] or {})
               for h in hist)


# ── actor identification: API keys ───────────────────────────────

def test_api_key_action_is_attributed_to_the_key(client, make_world):
    w = make_world()
    key = client.post("/api/access/api-keys", headers=w["admin"],
                      json={"name": "ci-bot"}).json()["api_key"]
    hdr = {"X-API-Key": key}

    up = client.post("/api/documents/upload", headers=hdr,
                     files={"files": ("r.txt", b"data", "text/plain")},
                     data={"scope": "company"})
    assert up.status_code == 200

    row = client.get("/api/admin/audit?prefix=document.uploaded", headers=w["admin"]).json()[0]
    assert row["actor"] == "api-key:ci-bot"
    assert row["meta"].get("api_key_id")
    # and in the activity stream
    act = client.get("/api/admin/activity?actor=api-key:ci-bot", headers=w["admin"]).json()
    assert act and act[0]["actor"] == "api-key:ci-bot"


# ── administrative activity is a first-class category ─────────────

def test_admin_writes_are_categorized_as_admin(client, make_world):
    w = make_world()
    client.put("/api/admin/settings", headers=w["admin"], json={"settings": {}})
    rows = client.get("/api/admin/activity?category=admin", headers=w["admin"]).json()
    assert any(r["route"] == "/api/admin/settings" and r["method"] == "PUT" for r in rows)
    # a plain content read is NOT admin
    client.get("/api/documents", headers=w["alice"])
    reads = client.get("/api/admin/activity?category=read", headers=w["admin"]).json()
    assert any(r["route"] == "/api/documents" for r in reads)
