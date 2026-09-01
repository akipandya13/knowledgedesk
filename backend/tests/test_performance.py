"""Performance: DB pool + pragmas + composite indexes, tenant-config caching,
the shared pooled HTTP client, and the response-time-target (SLO) surface."""
from __future__ import annotations

import time

from sqlalchemy import text

from app import http_client
from app.cache import TTLCache, invalidate_tenant_config, tenant_config_cache
from app.config import get_settings
from app.database import SessionLocal, engine


# ── TTL cache ────────────────────────────────────────────────────

def test_ttlcache_caches_expires_and_evicts():
    c = TTLCache(ttl=0.2, maxsize=10)
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return calls["n"]

    assert c.get_or_set("k", factory) == 1
    assert c.get_or_set("k", factory) == 1          # hit
    assert calls["n"] == 1
    time.sleep(0.25)
    assert c.get_or_set("k", factory) == 2          # expired → recompute
    assert c.stats()["hits"] == 1 and c.stats()["misses"] == 2


def test_ttlcache_zero_ttl_is_a_passthrough():
    c = TTLCache(ttl=0)
    assert c.get_or_set("k", lambda: 1) == 1
    assert c.get_or_set("k", lambda: 2) == 2        # never cached


def test_ttlcache_invalidate_by_predicate():
    c = TTLCache(ttl=60)
    c.get_or_set((1, "a"), lambda: "x")
    c.get_or_set((2, "b"), lambda: "y")
    assert c.invalidate(lambda k: k[0] == 1) == 1
    assert c.stats()["size"] == 1


# ── tenant model-config cache ───────────────────────────────────

def test_resolve_model_config_is_cached_per_tenant(client, make_world):
    from app.tenant_settings import resolve_model_config
    from app.database import Tenant

    w = make_world()
    invalidate_tenant_config()
    db = SessionLocal()
    try:
        tenant = db.get(Tenant, w["tenant_id"])
        before = tenant_config_cache().stats()["misses"]
        a = resolve_model_config(tenant)
        b = resolve_model_config(tenant)              # hit
        assert a == b
        stats = tenant_config_cache().stats()
        assert stats["hits"] >= 1
        assert stats["misses"] == before + 1

        invalidate_tenant_config(w["tenant_id"])
        resolve_model_config(tenant)                  # miss again
        assert tenant_config_cache().stats()["misses"] == before + 2
    finally:
        db.close()


def test_settings_change_busts_the_config_cache(client, make_world):
    from app.tenant_settings import resolve_model_config
    from app.database import Tenant

    w = make_world()
    db = SessionLocal()
    try:
        tenant = db.get(Tenant, w["tenant_id"])
        first = resolve_model_config(tenant)
        assert first["retrieval_top_k"] != 7
    finally:
        db.close()

    client.put("/api/admin/settings", headers=w["admin"],
               json={"settings": {"model_profile": "demo_fast", "retrieval_top_k": 7}})

    db = SessionLocal()
    try:
        tenant = db.get(Tenant, w["tenant_id"])
        assert resolve_model_config(tenant)["retrieval_top_k"] == 7
    finally:
        db.close()


# ── DB pool + pragmas + indexes ─────────────────────────────────

def test_engine_pool_is_configured():
    assert engine.pool._pre_ping is True
    # recycle is set from config (SQLite pool still honours it)
    assert engine.pool._recycle == get_settings().db_pool_recycle


def test_sqlite_performance_pragmas_applied():
    db = SessionLocal()
    try:
        assert db.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"
        assert db.execute(text("PRAGMA temp_store")).scalar() in (2, "2")   # MEMORY
        cache = db.execute(text("PRAGMA cache_size")).scalar()
        assert cache < 0                              # negative → KB, i.e. our -N*1024
    finally:
        db.close()


def test_composite_indexes_exist():
    db = SessionLocal()
    try:
        names = {r[0] for r in db.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()}
    finally:
        db.close()
    for expected in ("ix_documents_tenant_active_status",
                     "ix_query_log_tenant_created",
                     "ix_audit_log_tenant_id_desc",
                     "ix_activity_log_tenant_user_id",
                     "ix_refresh_tokens_user_revoked"):
        assert expected in names, expected


# ── shared pooled HTTP client ───────────────────────────────────

def test_http_client_is_shared_and_recreated_after_close():
    a = http_client.get_client()
    b = http_client.get_client()
    assert a is b
    http_client.close()
    c = http_client.get_client()
    assert c is not a and not c.is_closed


def test_async_http_client_is_shared():
    import asyncio

    async def _two():
        return http_client.get_async_client(), http_client.get_async_client()

    x, y = asyncio.run(_two())
    assert x is y


# ── SLO / response-time targets ─────────────────────────────────

def test_slo_endpoint_reports_targets_from_config(client, make_world):
    w = make_world()
    client.get("/api/health")                     # guarantee an api-latency sample
    r = client.get("/api/observability/slo", headers=w["admin"])
    assert r.status_code == 200
    body = r.json()
    by = {t["name"]: t for t in body["targets"]}
    assert set(by) == {"api", "rag_answer", "ingest_document"}
    assert by["api"]["target_p95_ms"] == get_settings().slo_api_p95_ms
    assert by["rag_answer"]["target_p95_ms"] == get_settings().slo_rag_answer_p95_ms
    assert by["api"]["samples"] >= 1              # from the /api/health call above
    assert by["api"]["p95_ms"] is not None
    assert isinstance(body["ok"], bool)
    assert isinstance(by["api"]["met"], bool)


def test_slo_endpoint_requires_observability_read(client, make_world):
    w = make_world()
    assert client.get("/api/observability/slo", headers=w["alice"]).status_code == 403


def test_slo_report_emits_gauges():
    from app import observability as obs
    from app.observability.slo import slo_report
    slo_report(emit=True)
    names = {m["name"] for m in obs.snapshot()["metrics"]}
    assert "slo.target.seconds" in names
    assert "slo.compliant" in names
