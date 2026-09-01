"""Structured logging: JSON formatter, correlation ids, the observability
bridge (WARNING+ → centralized sinks), the global error handler, and the
optional Postgres/Mongo centralized-collection sinks (driver mocked — no
real database needed)."""
from __future__ import annotations

import logging

import pytest

from app import logging_setup
from app.observability import context as obs_ctx


# ── JSON formatter + correlation ───────────────────────────────────

def _make_record(msg="hello", level=logging.INFO, exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="knowledgedesk.test", level=level, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=exc_info)


def test_correlation_filter_stamps_bound_context():
    tokens = obs_ctx.bind(request_id="rid-1", tenant="acme", actor="alice@acme.test", route="/api/x")
    try:
        record = _make_record()
        assert logging_setup.CorrelationFilter().filter(record) is True
        assert record.request_id == "rid-1"
        assert record.tenant == "acme"
        assert record.actor == "alice@acme.test"
        assert record.route == "/api/x"
    finally:
        obs_ctx.unbind(tokens)


def test_correlation_filter_defaults_outside_a_request():
    record = _make_record()
    logging_setup.CorrelationFilter().filter(record)
    assert record.request_id == "-"


def test_json_formatter_shape_and_correlation(monkeypatch):
    import json
    tokens = obs_ctx.bind(request_id="rid-2", tenant="acme", actor="bob")
    try:
        record = _make_record(msg="something happened")
        logging_setup.CorrelationFilter().filter(record)
        out = json.loads(logging_setup.JsonFormatter(service="kd", environment="test").format(record))
        assert out["message"] == "something happened"
        assert out["level"] == "INFO"
        assert out["request_id"] == "rid-2"
        assert out["tenant"] == "acme"
        assert out["actor"] == "bob"
        assert out["route"] is None                # unbound field -> null, not "-"
        assert out["service"] == "kd" and out["environment"] == "test"
    finally:
        obs_ctx.unbind(tokens)


def test_json_formatter_includes_exc_info():
    import json
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = _make_record(msg="failed", level=logging.ERROR, exc_info=sys.exc_info())
    logging_setup.CorrelationFilter().filter(record)
    out = json.loads(logging_setup.JsonFormatter(service="kd", environment="test").format(record))
    assert "ValueError: boom" in out["exc_info"]


# ── the observability bridge ────────────────────────────────────────

def test_bridge_forwards_warnings_as_app_log_event(client, make_world):
    w = make_world()   # superadmin's query is unscoped — sees events bound to no tenant too
    log = logging.getLogger("knowledgedesk.test.bridge")
    log.warning("a bridged warning for the centralized log store")

    rows = client.get("/api/observability/events?kind=app.log",
                      headers=w["superadmin"]).json()["events"]
    assert any("bridged warning" in r["fields"].get("message", "") for r in rows)


def test_bridge_ignores_info_level(client, make_world):
    w = make_world()
    before = len(client.get("/api/observability/events?kind=app.log",
                            headers=w["superadmin"]).json()["events"])
    logging.getLogger("knowledgedesk.test.bridge").info("just an info line, should not bridge")
    after = client.get("/api/observability/events?kind=app.log",
                       headers=w["superadmin"]).json()["events"]
    assert not any("should not bridge" in r["fields"].get("message", "") for r in after)
    assert len(after) == before


def test_bridge_excludes_the_observability_loggers_to_avoid_a_loop():
    handler = logging_setup.ObservabilityBridgeHandler(level=logging.WARNING)
    record = _make_record(msg="internal sink warning", level=logging.WARNING)
    record.name = "knowledgedesk.observability"
    calls = []
    import app.observability as obs
    orig = obs.event
    obs.event = lambda *a, **k: calls.append((a, k))
    try:
        handler.emit(record)
    finally:
        obs.event = orig
    assert calls == []


# ── global unhandled-exception handler ─────────────────────────────

def test_unhandled_exception_returns_safe_json_with_request_id(client, make_world, monkeypatch):
    # `client` just ensures the app's startup bootstrap (superadmin account) has
    # already run before make_world() looks it up; the assertions use a
    # dedicated client below so Starlette doesn't re-raise into the test.
    import app.main as main
    from starlette.testclient import TestClient

    w = make_world()

    def _boom(*a, **k):
        raise RuntimeError("very sensitive internal detail")

    monkeypatch.setattr("app.routers.admin.audit.list_entries", _boom)
    # The real ASGI/HTTP behaviour still returns our safe JSON response (Starlette
    # additionally re-raises into strict test clients so *they* can assert on it —
    # raise_server_exceptions=False observes what an actual caller receives).
    with TestClient(main.app, raise_server_exceptions=False) as c:
        r = c.get("/api/admin/audit", headers=w["admin"])
        assert r.status_code == 500
        body = r.json()
        assert body["detail"] == "Internal server error"
        assert "sensitive internal detail" not in r.text
        assert body.get("request_id")

        # top-level crashes aren't tenant-scoped (the handler runs outside the
        # request's own middleware stack) — visible platform-wide, like other
        # infra-level signals.
        events = c.get("/api/observability/events?kind=app.error",
                       headers=w["superadmin"]).json()["events"]
        assert any(e["fields"].get("error_type") == "RuntimeError" for e in events)
        assert any(e["actor"] == f"admin@{w['slug']}.test" for e in events)


# ── centralized collection sinks (driver mocked) ────────────────────

class _FakeCursor:
    def __init__(self, log):
        self._log = log
    def execute(self, sql, *a):
        self._log.append(("execute", sql))
    def executemany(self, sql, rows):
        self._log.append(("executemany", sql, list(rows)))
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self):
        self.calls: list = []
    def cursor(self):
        return _FakeCursor(self.calls)
    def close(self):
        self.calls.append(("close",))


def test_postgres_sink_batches_and_writes(monkeypatch):
    import types
    fake_conn = _FakeConn()
    fake_psycopg = types.SimpleNamespace(connect=lambda dsn, autocommit=True: fake_conn)
    monkeypatch.setitem(__import__("sys").modules, "psycopg", fake_psycopg)

    from app.observability.sinks.postgres import PostgresSink
    from app.observability.models import Event

    sink = PostgresSink(dsn="postgresql://x/y", table="kd_logs", batch=2)
    assert any(c[0] == "execute" for c in fake_conn.calls)   # DDL ran

    sink.on_event(Event(kind="test.one", fields={"a": 1}))
    assert not any(c[0] == "executemany" for c in fake_conn.calls)   # under batch size
    sink.on_event(Event(kind="test.two", fields={"a": 2}))
    assert any(c[0] == "executemany" for c in fake_conn.calls)       # flushed at batch=2

    sink.close()
    assert ("close",) in fake_conn.calls


def test_postgres_sink_rejects_bad_table_name():
    from app.observability.sinks.postgres import PostgresSink
    with pytest.raises(ValueError):
        PostgresSink(dsn="postgresql://x/y", table="kd_logs; drop table users;--")


def test_postgres_sink_requires_dsn():
    from app.observability.sinks.postgres import PostgresSink
    with pytest.raises(ValueError):
        PostgresSink(dsn="")


class _FakeCollection:
    def __init__(self):
        self.inserted: list = []
    def create_index(self, *a, **k):
        pass
    def insert_many(self, docs, ordered=False):
        self.inserted.extend(docs)


def test_mongo_sink_batches_and_writes(monkeypatch):
    import types
    fake_collection = _FakeCollection()

    class _FakeClient:
        def __init__(self, uri, **kw):
            pass
        def __getitem__(self, name):
            return {"logs": fake_collection}
        def close(self):
            pass

    fake_pymongo = types.SimpleNamespace(MongoClient=_FakeClient)
    monkeypatch.setitem(__import__("sys").modules, "pymongo", fake_pymongo)

    from app.observability.sinks.mongodb import MongoSink
    from app.observability.models import Event

    sink = MongoSink(uri="mongodb://x/y", database="db", collection="logs", batch=2)
    sink.on_event(Event(kind="test.one", fields={"a": 1}))
    assert fake_collection.inserted == []
    sink.on_event(Event(kind="test.two", fields={"a": 2}))
    assert len(fake_collection.inserted) == 2
    assert fake_collection.inserted[0]["sig"] == "event"


def test_mongo_sink_requires_uri():
    from app.observability.sinks.mongodb import MongoSink
    with pytest.raises(ValueError):
        MongoSink(uri="")


def test_sink_registry_knows_postgres_and_mongodb():
    from app.observability.sinks import SINK_BUILDERS
    assert "postgres" in SINK_BUILDERS
    assert "mongodb" in SINK_BUILDERS
