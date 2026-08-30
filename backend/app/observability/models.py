"""Signal value objects.

Three signal types flow through the facade:

  * Sample  — one metric observation (counter increment / gauge set / histogram
              observation), already carrying its resolved label set.
  * Event   — a structured domain event ("question.answered", "auth.login.failed").
  * Span    — a timed unit of work, optionally nested, for tracing a pipeline.

They are plain dataclasses so any sink can serialise them however it likes
(JSON lines, OTLP, a row in a table, a webhook body, …).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class MetricKind(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass(slots=True)
class Sample:
    name: str
    kind: MetricKind
    value: float
    labels: dict[str, str]
    ts: float = field(default_factory=time.time)


@dataclass(slots=True)
class Event:
    kind: str
    fields: dict
    level: str = "info"                 # info | warn | error
    request_id: str | None = None
    trace_id: str | None = None
    tenant: str | None = None
    actor: str | None = None
    route: str | None = None
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "level": self.level, "ts": self.ts,
            "request_id": self.request_id, "trace_id": self.trace_id,
            "tenant": self.tenant, "actor": self.actor, "route": self.route,
            "fields": self.fields,
        }


@dataclass(slots=True)
class Span:
    name: str
    span_id: str
    trace_id: str
    parent_id: str | None = None
    request_id: str | None = None
    tenant: str | None = None
    attributes: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    status: str = "ok"                  # ok | error
    start: float = field(default_factory=time.perf_counter)
    start_wall: float = field(default_factory=time.time)
    end: float | None = None
    duration_ms: float | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name, "span_id": self.span_id, "trace_id": self.trace_id,
            "parent_id": self.parent_id, "request_id": self.request_id,
            "tenant": self.tenant, "status": self.status,
            "start_wall": self.start_wall, "duration_ms": self.duration_ms,
            "attributes": self.attributes, "events": self.events,
        }
