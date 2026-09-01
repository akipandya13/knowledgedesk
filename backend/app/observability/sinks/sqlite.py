"""Self-contained SQLite sink — the built-in queryable backend.

Writes events and spans to a **separate** database (default
``{DATA_DIR}/observability.db``) so the feature is fully detachable: delete the
file and the package, nothing else is touched. Powers the
``/api/observability/events`` and ``/api/observability/traces/{id}`` endpoints
and the frontend panel, with time-based retention.

Synchronous writes, one connection guarded by a lock, WAL mode — fine for
pilot/enterprise-demo volumes (hundreds of signals/minute). Swap in the
`webhook`/`otlp` sinks (or your own) for high-throughput production.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time

from ...crypto import decrypt, encrypt
from ..models import Event, Span
from .base import Sink


def _enc(obj) -> str:
    return encrypt(json.dumps(obj, default=str)) or ""


def _dec(raw) -> dict:
    try:
        return json.loads(decrypt(raw) or "{}")
    except (ValueError, TypeError):
        return {}

log = logging.getLogger("knowledgedesk.observability")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS obs_events (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    level TEXT NOT NULL,
    tenant TEXT,
    actor TEXT,
    route TEXT,
    request_id TEXT,
    trace_id TEXT,
    fields_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_obs_events_ts ON obs_events(ts);
CREATE INDEX IF NOT EXISTS ix_obs_events_kind ON obs_events(kind);
CREATE INDEX IF NOT EXISTS ix_obs_events_tenant ON obs_events(tenant);

CREATE TABLE IF NOT EXISTS obs_spans (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    name TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_id TEXT,
    trace_id TEXT,
    request_id TEXT,
    tenant TEXT,
    status TEXT NOT NULL,
    duration_ms REAL,
    attributes_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_obs_spans_trace ON obs_spans(trace_id);
CREATE INDEX IF NOT EXISTS ix_obs_spans_ts ON obs_spans(ts);
"""


class SqliteSink(Sink):
    name = "sqlite"

    def __init__(self, *, path: str, retention_hours: int = 168):
        self._path = path
        self._retention = max(1, retention_hours) * 3600
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._last_prune = 0.0

    # ── ingest ────────────────────────────────────────────────────
    def on_event(self, e: Event) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO obs_events(ts,kind,level,tenant,actor,route,request_id,trace_id,fields_json)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (e.ts, e.kind, e.level, e.tenant, e.actor, e.route,
                     e.request_id, e.trace_id, _enc(e.fields)),
                )
                self._conn.commit()
                self._maybe_prune()
            except Exception:
                log.exception("observability sqlite event write failed")

    def on_span(self, sp: Span) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO obs_spans(ts,name,span_id,parent_id,trace_id,request_id,tenant,status,duration_ms,attributes_json)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (sp.start_wall, sp.name, sp.span_id, sp.parent_id, sp.trace_id,
                     sp.request_id, sp.tenant, sp.status, sp.duration_ms,
                     _enc(sp.attributes)),
                )
                self._conn.commit()
            except Exception:
                log.exception("observability sqlite span write failed")

    def _maybe_prune(self) -> None:
        now = time.time()
        if now - self._last_prune < 300:            # at most every 5 min
            return
        self._last_prune = now
        cutoff = now - self._retention
        self._conn.execute("DELETE FROM obs_events WHERE ts < ?", (cutoff,))
        self._conn.execute("DELETE FROM obs_spans WHERE ts < ?", (cutoff,))
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ── query helpers (used by the router) ───────────────────────
    def query_events(self, *, tenant: str | None = None, kind: str | None = None,
                     since: float | None = None, limit: int = 200) -> list[dict]:
        sql = ["SELECT ts,kind,level,tenant,actor,route,request_id,trace_id,fields_json FROM obs_events WHERE 1=1"]
        args: list = []
        if tenant is not None:
            sql.append("AND tenant = ?"); args.append(tenant)
        if kind:
            sql.append("AND kind = ?"); args.append(kind)
        if since:
            sql.append("AND ts >= ?"); args.append(since)
        sql.append("ORDER BY ts DESC LIMIT ?"); args.append(min(int(limit), 1000))
        with self._lock:
            rows = self._conn.execute(" ".join(sql), args).fetchall()
        return [{
            "ts": r[0], "kind": r[1], "level": r[2], "tenant": r[3], "actor": r[4],
            "route": r[5], "request_id": r[6], "trace_id": r[7],
            "fields": _dec(r[8]),
        } for r in rows]

    def query_trace(self, trace_id: str, *, tenant: str | None = None) -> list[dict]:
        sql = ["SELECT ts,name,span_id,parent_id,trace_id,request_id,tenant,status,duration_ms,attributes_json"
               " FROM obs_spans WHERE trace_id = ?"]
        args: list = [trace_id]
        if tenant is not None:
            sql.append("AND tenant = ?"); args.append(tenant)
        sql.append("ORDER BY ts ASC")
        with self._lock:
            rows = self._conn.execute(" ".join(sql), args).fetchall()
        return [{
            "ts": r[0], "name": r[1], "span_id": r[2], "parent_id": r[3],
            "trace_id": r[4], "request_id": r[5], "tenant": r[6], "status": r[7],
            "duration_ms": r[8], "attributes": _dec(r[9]),
        } for r in rows]
