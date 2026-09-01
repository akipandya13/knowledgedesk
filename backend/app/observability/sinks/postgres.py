"""Postgres sink — centralized, queryable log/event storage (SQL backend).

Batches ``Event`` / ``Span`` rows into one table (default ``kd_logs``),
auto-creating it on first connect. Pick this when a deployment already runs
Postgres and wants a durable, cross-instance, queryable store — instead of the
single-node, file-based ``sqlite`` sink. Selected purely by configuration
(``OBSERVABILITY_SINKS=...,postgres`` + ``OBS_POSTGRES_DSN``); nothing else in
the app knows a database is involved — same ``Sink`` contract as every other
backend (see ``sinks/__init__.py`` for how to add a different one instead).

The ``psycopg`` driver is imported lazily, inside ``__init__`` — the base
install has no hard dependency on Postgres; it is only required once this sink
is actually selected.
"""
from __future__ import annotations

import json
import logging
import re
import threading

from ..models import Event, Span
from .base import Sink

log = logging.getLogger("knowledgedesk.observability")

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    id BIGSERIAL PRIMARY KEY,
    ts DOUBLE PRECISION NOT NULL,
    sig TEXT NOT NULL,               -- event | span
    kind TEXT,
    level TEXT,
    tenant TEXT,
    actor TEXT,
    route TEXT,
    request_id TEXT,
    trace_id TEXT,
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_{table}_ts ON {table}(ts);
CREATE INDEX IF NOT EXISTS ix_{table}_kind ON {table}(kind);
CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table}(tenant);
"""


def _safe_table(name: str) -> str:
    name = (name or "kd_logs").strip()
    if not _IDENT.match(name):
        raise ValueError(f"OBS_POSTGRES_TABLE must be a plain identifier, got {name!r}")
    return name


class PostgresSink(Sink):
    name = "postgres"
    blocking = True          # network I/O — dispatcher feeds this off-thread

    def __init__(self, *, dsn: str, table: str = "kd_logs", batch: int = 50):
        if not dsn:
            raise ValueError("OBS_POSTGRES_DSN is required for the postgres sink")
        import psycopg                       # optional — only needed when selected
        self._table = _safe_table(table)
        self._batch_size = max(1, batch)
        self._lock = threading.Lock()
        self._buf: list[tuple] = []
        self._conn = psycopg.connect(dsn, autocommit=True)
        with self._conn.cursor() as cur:
            cur.execute(_DDL.format(table=self._table))

    def _row(self, sig: str, obj) -> tuple:
        d = obj.as_dict()
        return (d.get("ts", d.get("start_wall")), sig, d.get("kind", d.get("name")),
                d.get("level"), d.get("tenant"), d.get("actor"), d.get("route"),
                d.get("request_id"), d.get("trace_id"), json.dumps(d, default=str))

    def on_event(self, e: Event) -> None:
        self._add(self._row("event", e))

    def on_span(self, sp: Span) -> None:
        self._add(self._row("span", sp))

    def _add(self, row: tuple) -> None:
        with self._lock:
            self._buf.append(row)
            if len(self._buf) >= self._batch_size:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        if not self._buf:
            return
        rows, self._buf = self._buf, []
        try:
            with self._conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {self._table}"
                    "(ts,sig,kind,level,tenant,actor,route,request_id,trace_id,payload)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        except Exception:                    # a sink must never raise
            log.warning("observability postgres sink write failed (%d rows dropped)", len(rows))

    def close(self) -> None:
        self.flush()
        try:
            self._conn.close()
        except Exception:
            pass
