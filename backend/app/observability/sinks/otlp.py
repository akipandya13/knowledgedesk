"""OpenTelemetry (OTLP/HTTP) sink — experimental, dependency-free.

Exports **spans** to any OTLP/HTTP collector (`OBS_OTLP_ENDPOINT`, e.g.
``http://otel-collector:4318``) as protobuf-shaped JSON via httpx — no
`opentelemetry-sdk` dependency. From the collector, fan out to Jaeger, Tempo,
Honeycomb, Datadog, etc.

Scope kept deliberately small (resource + one scope + spans). Extend
``_span_to_otlp`` / add a metrics exporter as a client needs; that is the
"mould it" seam.
"""
from __future__ import annotations

import logging
import time

import httpx

from ..models import Span
from .base import Sink

log = logging.getLogger("knowledgedesk.observability")


def _hexpad(v: str, n: int) -> str:
    return (v or "0").replace("-", "").rjust(n, "0")[:n]


class OtlpSink(Sink):
    name = "otlp"
    blocking = True

    def __init__(self, *, endpoint: str, headers: str = "",
                 service_name: str = "knowledgedesk", timeout: float = 5.0):
        self._url = endpoint.rstrip("/") + "/v1/traces"
        self._timeout = timeout
        self._service = service_name
        self._headers = {"Content-Type": "application/json"}
        for pair in (headers or "").split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                self._headers[k.strip()] = v.strip()
        self._buf: list[dict] = []

    def _span_to_otlp(self, sp: Span) -> dict:
        start_ns = int(sp.start_wall * 1e9)
        end_ns = int((sp.start_wall + (sp.duration_ms or 0) / 1000) * 1e9)
        return {
            "traceId": _hexpad(sp.trace_id, 32),
            "spanId": _hexpad(sp.span_id, 16),
            "parentSpanId": _hexpad(sp.parent_id, 16) if sp.parent_id else "",
            "name": sp.name,
            "kind": 1,
            "startTimeUnixNano": str(start_ns),
            "endTimeUnixNano": str(end_ns),
            "attributes": [
                {"key": k, "value": {"stringValue": str(v)}}
                for k, v in {**sp.attributes, "tenant": sp.tenant or ""}.items()
            ],
            "status": {"code": 2 if sp.status == "error" else 1},
        }

    def on_span(self, sp: Span) -> None:
        self._buf.append(self._span_to_otlp(sp))
        if len(self._buf) >= 50:
            self.flush()

    def flush(self) -> None:
        if not self._buf:
            return
        spans, self._buf = self._buf, []
        payload = {"resourceSpans": [{
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": self._service}}
            ]},
            "scopeSpans": [{"scope": {"name": "knowledgedesk.observability"},
                            "spans": spans}],
        }]}
        try:
            httpx.post(self._url, json=payload, headers=self._headers, timeout=self._timeout)
        except Exception as exc:
            log.warning("observability OTLP export failed: %s", exc)

    def close(self) -> None:
        self.flush()
