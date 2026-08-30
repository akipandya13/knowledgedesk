"""Fan-out from the facade to the configured sinks.

Rules:
  * The metric registry is updated **synchronously** (cheap, lock-guarded) so
    `/metrics` and the JSON snapshot are always current.
  * Non-blocking sinks (stdout, sqlite, prometheus) are called inline.
  * Blocking sinks (webhook, otlp) are fed from a bounded queue drained by one
    daemon thread; on overflow the oldest item is dropped and counted.
  * Nothing here ever raises into the caller — every sink call is guarded.
"""
from __future__ import annotations

import logging
import queue
import threading

from .models import Event, Sample, Span
from .registry import Registry
from .sinks.base import Sink

log = logging.getLogger("knowledgedesk.observability")

_QUEUE_MAX = 10_000


class Dispatcher:
    def __init__(self, registry: Registry, sinks: list[Sink]):
        self.registry = registry
        self._sync = [s for s in sinks if not s.blocking]
        self._async = [s for s in sinks if s.blocking]
        self._q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        self._dropped = 0
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        if self._async:
            self._worker = threading.Thread(target=self._run, name="obs-dispatch", daemon=True)
            self._worker.start()

    # ── inbound ──────────────────────────────────────────────────
    def metric(self, s: Sample, **meta) -> None:
        try:
            self.registry.record(s, **meta)
        except Exception:
            log.exception("observability registry.record failed")
        self._fan(("metric", s))

    def event(self, e: Event) -> None:
        self._fan(("event", e))

    def span(self, sp: Span) -> None:
        self._fan(("span", sp))

    # ── fan-out ──────────────────────────────────────────────────
    def _fan(self, item) -> None:
        for sink in self._sync:
            _deliver(sink, item)
        if self._async:
            try:
                self._q.put_nowait(item)
            except queue.Full:
                try:
                    self._q.get_nowait()          # drop oldest
                    self._q.put_nowait(item)
                except queue.Empty:
                    pass
                self._dropped += 1

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            for sink in self._async:
                _deliver(sink, item)

    # ── lifecycle ────────────────────────────────────────────────
    def flush(self) -> None:
        for sink in (*self._sync, *self._async):
            try:
                sink.flush()
            except Exception:
                log.exception("observability sink.flush failed")

    def close(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=2)
        for sink in (*self._sync, *self._async):
            try:
                sink.flush()
                sink.close()
            except Exception:
                log.exception("observability sink.close failed")

    @property
    def dropped(self) -> int:
        return self._dropped


def _deliver(sink: Sink, item) -> None:
    kind, payload = item
    try:
        if kind == "metric":
            sink.on_metric(payload)
        elif kind == "event":
            sink.on_event(payload)
        else:
            sink.on_span(payload)
    except Exception:
        log.exception("observability sink '%s' raised on %s", getattr(sink, "name", "?"), kind)
