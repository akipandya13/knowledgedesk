"""Resilience: retries, timeouts, idempotency, startup recovery, backup/restore."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import sys
import tarfile
import tempfile

import pytest

from app import recovery
from app.config import get_settings
from app.database import (ApiKey, AuthToken, ConnectorSyncRun, Document,
                          SessionLocal, Tenant, User, utcnow)
from app.resilience import RetryError, aretry_call, retry_call


# ── retry helper ─────────────────────────────────────────────────

def test_retry_call_recovers_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("blip")
        return "ok"

    assert retry_call(flaky, op="test.flaky", retry_on=(ConnectionError,),
                      attempts=5, base_delay=0.0, max_delay=0.0) == "ok"
    assert calls["n"] == 3


def test_retry_call_gives_up_and_wraps_the_last_error():
    with pytest.raises(RetryError) as ei:
        retry_call(lambda: (_ for _ in ()).throw(TimeoutError("down")),
                   op="test.down", retry_on=(TimeoutError,), attempts=3,
                   base_delay=0.0, max_delay=0.0)
    assert isinstance(ei.value.__cause__, TimeoutError)


def test_retry_call_does_not_retry_unlisted_exceptions():
    calls = {"n": 0}

    def bad():
        calls["n"] += 1
        raise ValueError("deterministic")

    with pytest.raises(ValueError):
        retry_call(bad, op="test.bad", retry_on=(ConnectionError,), attempts=4)
    assert calls["n"] == 1


def test_aretry_call_recovers():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("blip")
        return 42

    assert asyncio.run(aretry_call(flaky, op="t.a", retry_on=(ConnectionError,),
                                   attempts=3, base_delay=0.0, max_delay=0.0)) == 42


# ── sqlite hardening ─────────────────────────────────────────────

def test_sqlite_busy_timeout_is_applied():
    db = SessionLocal()
    try:
        from sqlalchemy import text
        val = db.execute(text("PRAGMA busy_timeout")).scalar()
        assert val == get_settings().sqlite_busy_timeout_ms
    finally:
        db.close()


# ── request timeout middleware ───────────────────────────────────

def test_slow_request_returns_504(client, make_world, monkeypatch):
    w = make_world()
    s = get_settings()
    monkeypatch.setattr(s, "request_timeout_seconds", 1)

    def _slow(*a, **k):
        import time
        time.sleep(2.5)
        return []

    monkeypatch.setattr("app.routers.admin.audit.list_entries", _slow)
    r = client.get("/api/admin/audit", headers=w["admin"])
    assert r.status_code == 504
    body = r.json()
    assert body["detail"] == "Request timed out"
    assert "request_id" in body


def test_timeout_disabled_when_zero(client, make_world, monkeypatch):
    w = make_world()
    monkeypatch.setattr(get_settings(), "request_timeout_seconds", 0)
    # a normal fast call is unaffected
    assert client.get("/api/admin/audit", headers=w["admin"]).status_code == 200


# ── idempotency ─────────────────────────────────────────────────

def test_idempotency_key_replays_and_does_not_act_twice(client, make_world):
    w = make_world()
    hdrs = {**w["admin"], "Idempotency-Key": "make-one-key-please"}

    r1 = client.post("/api/access/api-keys", headers=hdrs, json={"name": "ci"})
    assert r1.status_code == 200
    first = r1.json()["api_key"]

    r2 = client.post("/api/access/api-keys", headers=hdrs, json={"name": "ci"})
    assert r2.status_code == 200
    assert r2.headers.get("Idempotency-Replayed") == "true"
    assert r2.json()["api_key"] == first          # same response, not a new key

    db = SessionLocal()
    try:
        n = db.query(ApiKey).filter(ApiKey.tenant_id == w["tenant_id"],
                                    ApiKey.name == "ci").count()
        assert n == 1
    finally:
        db.close()


def test_idempotency_key_reused_with_different_body_is_409(client, make_world):
    w = make_world()
    hdrs = {**w["admin"], "Idempotency-Key": "reused-key-x"}
    assert client.post("/api/access/api-keys", headers=hdrs, json={"name": "a"}).status_code == 200
    r = client.post("/api/access/api-keys", headers=hdrs, json={"name": "b"})
    assert r.status_code == 409


def test_no_idempotency_key_is_normal(client, make_world):
    w = make_world()
    a = client.post("/api/access/api-keys", headers=w["admin"], json={"name": "k1"})
    b = client.post("/api/access/api-keys", headers=w["admin"], json={"name": "k2"})
    assert a.json()["api_key"] != b.json()["api_key"]


# ── startup recovery reconciler ──────────────────────────────────

def test_reconcile_closes_out_interrupted_work(client, make_world):
    w = make_world()
    old = utcnow() - dt.timedelta(hours=2)
    db = SessionLocal()
    try:
        stuck_doc = Document(tenant_id=w["tenant_id"], filename="wedged.txt",
                             status="processing", created_at=old)
        fresh_doc = Document(tenant_id=w["tenant_id"], filename="ok.txt",
                             status="processing", created_at=utcnow())
        stuck_run = ConnectorSyncRun(connector_id=1, tenant_id=w["tenant_id"],
                                     status="running", started_at=old)
        dead_token = AuthToken(user_id=w["ids"]["alice"], purpose="reset_password",
                               token_hash="x" * 10, expires_at=old)
        db.add_all([stuck_doc, fresh_doc, stuck_run, dead_token])
        db.commit()
        stuck_id, fresh_id, run_id = stuck_doc.id, fresh_doc.id, stuck_run.id
    finally:
        db.close()

    tally = recovery.reconcile_on_startup(SessionLocal())
    assert tally.get("documents_failed", 0) >= 1
    assert tally.get("sync_runs_failed", 0) >= 1
    assert tally.get("auth_tokens_pruned", 0) >= 1

    db = SessionLocal()
    try:
        assert db.get(Document, stuck_id).status == "failed"
        assert "Interrupted" in db.get(Document, stuck_id).error
        assert db.get(Document, fresh_id).status == "processing"   # recent → left alone
        assert db.get(ConnectorSyncRun, run_id).status == "failed"
    finally:
        db.close()


# ── backup / restore ─────────────────────────────────────────────

def test_backup_creates_a_verifiable_archive(client, make_world, tmp_path, monkeypatch):
    make_world()
    monkeypatch.setattr("scripts.backup._qdrant_snapshots",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no qdrant in test")))
    from scripts.backup import main as backup_main
    assert backup_main(["--out", str(tmp_path)]) == 0

    archives = list(tmp_path.glob("kd-backup-*.tar.gz"))
    assert len(archives) == 1
    with tarfile.open(archives[0]) as tar:
        names = tar.getnames()
        assert "manifest.json" in names
        assert "db/knowledgedesk.db" in names
        manifest = json.load(tar.extractfile("manifest.json"))
    assert manifest["version"] == 1
    assert "db/knowledgedesk.db" in manifest["files"]
    assert any("Qdrant snapshot failed" in n for n in manifest["notes"])


def test_restore_refuses_a_populated_db_without_force(client, make_world, tmp_path, monkeypatch):
    make_world()
    monkeypatch.setattr("scripts.backup._qdrant_snapshots", lambda *a, **k: [])
    from scripts.backup import main as backup_main
    from scripts.restore import main as restore_main
    backup_main(["--out", str(tmp_path)])
    archive = str(next(tmp_path.glob("kd-backup-*.tar.gz")))

    # the test DB already has tables → restore must refuse without --force
    rc = restore_main(["--archive", archive, "--yes"])
    assert rc == 2

    # dry run (no --yes) always exits 0 after verifying the manifest
    assert restore_main(["--archive", archive]) == 0
