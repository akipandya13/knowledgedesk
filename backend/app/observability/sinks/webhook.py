"""Batching HTTP webhook sink.

POSTs newline-delimited JSON batches to an arbitrary URL — feed a client's
collector, a serverless function, an SIEM HTTP endpoint, etc. Runs off-thread
(``blocking = True``); on overload the dispatcher drops oldest and counts it.
"""
from __future__ import annotations

import json
import logging

import httpx

from ..models import Event, Sample, Span
from .base import Sink

log = logging.getLogger("knowledgedesk.observability")


class WebhookSink(Sink):
    name = "webhook"
    blocking = True

    def __init__(self, *, url: str, token: str = "", batch: int = 100,
                 timeout: float = 5.0, send_metrics: bool = False):
        self._url = url
        self._headers = {"Content-Type": "application/x-ndjson"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._batch_size = max(1, batch)
        self._timeout = timeout
        self._send_metrics = send_metrics
        self._buf: list[dict] = []

    def _add(self, row: dict) -> None:
        self._buf.append(row)
        if len(self._buf) >= self._batch_size:
            self.flush()

    def on_event(self, e: Event) -> None:
        self._add({"sig": "event", **e.as_dict()})

    def on_span(self, sp: Span) -> None:
        self._add({"sig": "span", **sp.as_dict()})

    def on_metric(self, s: Sample) -> None:
        if self._send_metrics:
            self._add({"sig": "metric", "name": s.name, "kind": s.kind.value,
                       "value": s.value, "labels": s.labels, "ts": s.ts})

    def flush(self) -> None:
        if not self._buf:
            return
        body = "\n".join(json.dumps(r, default=str) for r in self._buf)
        self._buf = []
        try:
            httpx.post(self._url, content=body, headers=self._headers, timeout=self._timeout)
        except Exception as exc:              # a sink must never raise
            log.warning("observability webhook POST failed: %s", exc)

    def close(self) -> None:
        self.flush()
