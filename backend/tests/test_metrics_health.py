"""Metrics (application + infrastructure/resource) and the liveness /
readiness / dependency-health probes."""
from __future__ import annotations

import asyncio

from app import health
from app import observability as obs
from app.observability import resources


# ── liveness ──────────────────────────────────────────────────────

def test_livez_is_cheap_and_always_ok(client):
    r = client.get("/livez")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "alive"
    assert "uptime_seconds" in body
    assert "dependencies" not in body        # no I/O, no dependency checks


def test_healthz_is_an_alias_of_livez(client):
    assert client.get("/healthz").json()["status"] == "alive"


def test_livez_is_not_swallowed_by_the_spa_fallback(client):
    # a bare non-/api path would otherwise return index.html with 200
    assert client.get("/livez").headers["content-type"].startswith("application/json")


# ── readiness ─────────────────────────────────────────────────────

def test_readyz_ok_when_required_dependencies_are_up(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert body["bootstrap_complete"] is True
    names = {d["name"] for d in body["dependencies"]}
    assert {"db", "qdrant", "llm"} <= names
    db_dep = next(d for d in body["dependencies"] if d["name"] == "db")
    assert db_dep["required"] is True and db_dep["status"] == "ok"
    # llm being down must NOT block readiness — it degrades to extractive
    llm_dep = next(d for d in body["dependencies"] if d["name"] == "llm")
    assert llm_dep["required"] is False


def test_readyz_503_when_a_required_dependency_is_down(client, monkeypatch):
    monkeypatch.setattr("app.health.vectorstore.healthy", lambda: False)
    r = client.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    qd = next(d for d in body["dependencies"] if d["name"] == "qdrant")
    assert qd["status"] == "down"


def test_readyz_emits_app_ready_and_dependency_metrics(client):
    client.get("/readyz")
    names = {m["name"] for m in obs.snapshot()["metrics"]}
    assert "app.ready" in names
    assert "dependency.up" in names
    assert "dependency.check.seconds" in names


# ── /api/health detailed view ────────────────────────────────────

def test_api_health_is_enriched_but_keeps_back_compat_keys(client):
    body = client.get("/api/health").json()
    # back-compat
    assert body["app"] == "ok"
    assert body["qdrant"] in ("ok", "down", "unknown")
    assert "llm_provider" in body and "llm_model" in body
    assert body["environment"]
    # new
    assert body["ready"] is True
    assert isinstance(body["dependencies"], list)
    assert {"db", "qdrant", "llm"} <= {d["name"] for d in body["dependencies"]}
    assert "resources" in body and isinstance(body["resources"], dict)
    for d in body["dependencies"]:
        assert "latency_ms" in d and "required" in d


# ── dependency probes ────────────────────────────────────────────

def test_check_dependencies_times_each_probe():
    deps = asyncio.run(health.check_dependencies())
    by = {d["name"]: d for d in deps}
    assert by["db"]["status"] == "ok"
    assert by["db"]["required"] is True
    assert by["qdrant"]["required"] is True
    assert by["llm"]["required"] is False
    assert all(isinstance(d["latency_ms"], (int, float)) for d in deps)


# ── infrastructure / resource-utilization metrics ────────────────

def test_resource_collector_emits_process_and_system_gauges():
    resources.collect_resource_metrics()
    names = {m["name"] for m in obs.snapshot()["metrics"]}
    # runtime metrics are always available
    assert "process.threads" in names
    assert "python.gc.objects" in names
    assert "process.uptime.seconds" in names
    # psutil is in requirements, so these should be present in CI too
    assert "process.memory.rss.bytes" in names
    assert "process.cpu.percent" in names
    assert "system.memory.percent" in names


def test_resource_gauges_have_sane_values():
    resources.collect_resource_metrics()
    by_name = {m["name"]: m for m in obs.snapshot()["metrics"]}
    rss = by_name["process.memory.rss.bytes"]["series"][0]["value"]
    assert rss > 1_000_000                                   # at least ~1 MB resident
    threads = by_name["process.threads"]["series"][0]["value"]
    assert threads >= 1


def test_resource_snapshot_shape():
    snap = resources.resource_snapshot()
    assert "threads" in snap
    assert snap.get("memory_rss_bytes", 1) > 0
