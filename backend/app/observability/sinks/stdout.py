"""Structured JSON-lines to the process logger.

Every signal becomes one line: ``{"sig":"event","kind":"question.answered",...}``.
Pair with any log shipper (Loki, CloudWatch, Datadog agent, ELK) — no code here
needs to know which.
"""
from __future__ import annotations

import json
import logging

from ..models import Event, Sample, Span
from .base import Sink

log = logging.getLogger("knowledgedesk.observability")


class StdoutSink(Sink):
    name = "stdout"

    def __init__(self, *, pretty: bool = False, metrics: bool = False):
        self._pretty = pretty
        self._metrics = metrics          # metrics are noisy; opt-in

    def _emit(self, payload: dict) -> None:
        try:
            log.info(json.dumps(payload, default=str,
                                indent=2 if self._pretty else None,
                                ensure_ascii=False))
        except Exception:                # never let logging break a request
            log.exception("observability stdout sink failed")

    def on_metric(self, s: Sample) -> None:
        if self._metrics:
            self._emit({"sig": "metric", "name": s.name, "kind": s.kind.value,
                        "value": s.value, "labels": s.labels, "ts": s.ts})

    def on_event(self, e: Event) -> None:
        self._emit({"sig": "event", **e.as_dict()})

    def on_span(self, sp: Span) -> None:
        self._emit({"sig": "span", **sp.as_dict()})
