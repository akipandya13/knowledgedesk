"""Observability facade, registry, HTTP middleware and read APIs."""
from __future__ import annotations

import time

import pytest

from app import observability as obs


# ── facade + registry ─────────────────────────────────────────────

def test_counter_gauge_histogram_aggregate_in_registry():
    obs.count("test.counter", 2, kind="unit")
    obs.count("test.counter", 3, kind="unit")
    obs.gauge("test.gauge", 7, host="a")
    for v in (0.01, 0.2, 3.0):
        obs.observe("test.hist.seconds", v, op="x")

    snap = obs.snapshot()
    by_name = {m["name"]: m for m in snap["metrics"]}

    c = by_name["test.counter"]["series"][0]
    assert c["labels"] == {"kind": "unit"} and c["value"] == 5

    g = by_name["test.gauge"]["series"][0]
    assert g["value"] == 7

    h = by_name["test.hist.seconds"]["series"][0]
    assert h["count"] == 3 and abs(h["sum"] - 3.21) < 1e-6
    assert h["buckets"]["0.25"] == 2          # 0.01 and 0.2 fall under 0.25


def test_disabled_facade_is_a_noop(monkeypatch):
    monkeypatch.setattr(obs, "_enabled", False)
    obs.count("should.not.appear")
    monkeypatch.setattr(obs, "_enabled", True)
    names = {m["name"] for m in obs.snapshot()["metrics"]}
    assert "should.not.appear" not in names


def test_span_records_duration_and_status():
    with obs.span("unit.span") as sp:
        sp.set(foo="bar")
        time.sleep(0.005)
    metrics = {m["name"] for m in obs.snapshot()["metrics"]}
    assert "span.duration.seconds" in metrics


def test_span_marks_error_on_exception():
    try:
        with obs.span("unit.boom"):
            raise ValueError("nope")
    except ValueError:
        pass
    hist = next(m for m in obs.snapshot()["metrics"] if m["name"] == "span.duration.seconds")
    assert any(s["labels"].get("status") == "error" for s in hist["series"])


def test_prometheus_render_shapes():
    obs.count("prom.render.total", 1, route="/x")
    text = obs.render_prometheus()
    assert "# TYPE prom_render_total counter" in text
    assert 'prom_render_total{route="/x"}' in text


# ── HTTP middleware ───────────────────────────────────────────────

def test_middleware_sets_request_id_and_records_http_metric(client):
    r = client.get("/api/health")
    assert r.headers.get("X-Request-ID")
    names = {m["name"] for m in obs.snapshot()["metrics"]}
    assert "http.server.requests" in names
    assert "http.server.duration.seconds" in names


def test_incoming_request_id_is_propagated(client):
    r = client.get("/api/health", headers={"X-Request-ID": "trace-abc-123"})
    assert r.headers["X-Request-ID"] == "trace-abc-123"


# ── read APIs + RBAC ─────────────────────────────────────────────

def test_metrics_api_requires_observability_read(client, make_world):
    w = make_world()
    assert client.get("/api/observability/metrics", headers=w["alice"]).status_code == 403
    assert client.get("/api/observability/metrics", headers=w["admin"]).status_code == 200
    assert client.get("/api/observability/metrics", headers=w["superadmin"]).status_code == 200


def test_metrics_api_is_tenant_scoped(client, make_world):
    w = make_world()
    with obs.bound(tenant=w["slug"]):
        obs.count("scoped.metric", 1)
    obs.count("other.metric", 1, tenant="someone-else")

    admin_view = client.get("/api/observability/metrics", headers=w["admin"]).json()
    series = {m["name"]: m["series"] for m in admin_view["metrics"]}
    # a series labelled with another tenant is filtered out for a workspace admin
    assert all(s["labels"].get("tenant") in (None, w["slug"])
               for m in admin_view["metrics"] for s in m["series"])

    su_view = client.get("/api/observability/metrics", headers=w["superadmin"]).json()
    assert any(s["labels"].get("tenant") == "someone-else"
               for m in su_view["metrics"] if m["name"] == "other.metric"
               for s in m["series"])


def test_events_api_returns_domain_events_from_sqlite(client, make_world):
    w = make_world()
    with obs.bound(tenant=w["slug"], actor="alice@x"):
        obs.event("unit.test.event", answer="42")

    r = client.get("/api/observability/events?kind=unit.test.event", headers=w["admin"])
    assert r.status_code == 200
    events = r.json()["events"]
    assert events and events[0]["kind"] == "unit.test.event"
    assert events[0]["tenant"] == w["slug"]
    assert events[0]["fields"]["answer"] == "42"

    # a member cannot read the events API at all
    assert client.get("/api/observability/events", headers=w["alice"]).status_code == 403


def test_trace_api_returns_spans_for_a_request(client, make_world):
    w = make_world()
    with obs.bound(request_id="req-xyz", tenant=w["slug"]):
        with obs.span("unit.trace.parent"):
            with obs.span("unit.trace.child"):
                pass
    obs.flush()
    r = client.get("/api/observability/traces/req-xyz", headers=w["admin"])
    assert r.status_code == 200
    names = {s["name"] for s in r.json()["spans"]}
    assert {"unit.trace.parent", "unit.trace.child"} <= names


def test_config_api_lists_active_sinks(client, make_world):
    w = make_world()
    cfg = client.get("/api/observability/config", headers=w["admin"]).json()
    assert cfg["enabled"] is True
    assert "sqlite" in cfg["sinks"]


def test_prometheus_endpoint_gated_by_sink(client, monkeypatch):
    # conftest enables only stdout+sqlite → /metrics is 404
    assert client.get("/metrics").status_code == 404
    monkeypatch.setattr("app.observability.active_sinks", lambda: ["prometheus", "sqlite"])
    body = client.get("/metrics")
    assert body.status_code == 200
    assert "# TYPE" in body.text
