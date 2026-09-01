"""MongoDB sink — centralized, queryable log/event storage (NoSQL backend).

Same role as the ``postgres`` sink for a NoSQL-first deployment: batches
``Event`` / ``Span`` documents into one collection (default ``logs``).
Selected purely by configuration (``OBSERVABILITY_SINKS=...,mongodb`` +
``OBS_MONGO_URI``); nothing else in the app knows a database is involved.

The ``pymongo`` driver is imported lazily, inside ``__init__`` — the base
install has no hard dependency on Mongo; it is only required once this sink is
actually selected.
"""
from __future__ import annotations

import logging
import threading

from ..models import Event, Span
from .base import Sink

log = logging.getLogger("knowledgedesk.observability")


class MongoSink(Sink):
    name = "mongodb"
    blocking = True          # network I/O — dispatcher feeds this off-thread

    def __init__(self, *, uri: str, database: str = "knowledgedesk",
                collection: str = "logs", batch: int = 50):
        if not uri:
            raise ValueError("OBS_MONGO_URI is required for the mongodb sink")
        import pymongo                       # optional — only needed when selected
        self._client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._collection = self._client[database][collection]
        self._collection.create_index([("ts", -1)])
        self._collection.create_index("kind")
        self._collection.create_index("tenant")
        self._batch_size = max(1, batch)
        self._lock = threading.Lock()
        self._buf: list[dict] = []

    def on_event(self, e: Event) -> None:
        self._add({"sig": "event", **e.as_dict()})

    def on_span(self, sp: Span) -> None:
        self._add({"sig": "span", **sp.as_dict()})

    def _add(self, doc: dict) -> None:
        with self._lock:
            self._buf.append(doc)
            if len(self._buf) >= self._batch_size:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        if not self._buf:
            return
        docs, self._buf = self._buf, []
        try:
            self._collection.insert_many(docs, ordered=False)
        except Exception:                    # a sink must never raise
            log.warning("observability mongodb sink write failed (%d docs dropped)", len(docs))

    def close(self) -> None:
        self.flush()
        try:
            self._client.close()
        except Exception:
            pass
