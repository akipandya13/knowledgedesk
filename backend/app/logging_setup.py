"""Process-wide structured logging.

Every stdlib ``logging`` record — this app's modules, its dependencies, and
uvicorn's own access/error logs — is emitted as **one JSON line** carrying the
same correlation ids (``request_id`` / ``trace_id`` / ``tenant`` / ``actor`` /
``route``) that :mod:`app.observability` attaches to events and spans, so a log
line and the domain event for the same request line up in whatever aggregator
reads stdout (Loki, Fluent Bit, CloudWatch, ELK, `docker compose logs`, …).

This is deliberately a separate concern from ``app.observability``'s own
``stdout`` sink (which prints *domain signals* — events/spans/metrics, tagged
``"sig"``); this module governs **log records** — everything written with
``logging.getLogger(...).info/warning/error(...)``, including uncaught
exceptions and third-party library output. Both land as JSON lines on the same
stream, so one log-shipper config collects everything.

Design notes
------------
* **Correlation via a Filter, not thread state.** :class:`CorrelationFilter`
  reads the same contextvars the HTTP middleware binds
  (``app.observability.context``) and stamps them onto every
  :class:`logging.LogRecord` before formatting — no call site changes needed.
* **Centralized collection without a second pipeline.** WARNING+ records are
  mirrored into ``app.observability`` as an ``app.log`` event
  (:class:`ObservabilityBridgeHandler`), so they reach every configured sink —
  including the ``postgres`` / ``mongodb`` sinks a deployment can opt into for
  a queryable, centralized log store. The observability subsystem's own
  loggers are excluded to prevent a feedback loop with the ``stdout`` sink.
* **Configuration wins, not code.** ``LOG_LEVEL`` / ``LOG_FORMAT`` /
  ``LOG_BRIDGE_LEVEL`` are the only knobs; see docs/LOGGING.md.
"""
from __future__ import annotations

import json
import logging
import sys

from .observability import context as obs_ctx

_OBS_LOGGER_PREFIX = "knowledgedesk.observability"


class CorrelationFilter(logging.Filter):
    """Stamps the ambient request/trace/tenant/actor onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        snap = obs_ctx.current()
        record.request_id = snap.request_id or "-"
        record.trace_id = snap.request_id or "-"
        record.tenant = snap.tenant or "-"
        record.actor = snap.actor or "-"
        record.route = snap.route or "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per log line."""

    def __init__(self, *, service: str, environment: str):
        super().__init__()
        self._service = service
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
            "service": self._service,
            "environment": self._environment,
            "request_id": _none_if_dash(getattr(record, "request_id", None)),
            "trace_id": _none_if_dash(getattr(record, "trace_id", None)),
            "tenant": _none_if_dash(getattr(record, "tenant", None)),
            "actor": _none_if_dash(getattr(record, "actor", None)),
            "route": _none_if_dash(getattr(record, "route", None)),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        # Ad-hoc structured context: logging.info(..., extra={"fields": {...}})
        extra = getattr(record, "fields", None)
        if extra:
            payload["fields"] = extra
        return json.dumps(payload, default=str, ensure_ascii=False)


def _none_if_dash(v):
    return None if v in (None, "-") else v


class TextFormatter(logging.Formatter):
    """Human-readable line for local development (``LOG_FORMAT=text``)."""

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s %(levelname)-8s %(name)s [req=%(request_id)s tenant=%(tenant)s] %(message)s",
        )


class ObservabilityBridgeHandler(logging.Handler):
    """Mirrors WARNING+ log records into the observability event stream.

    This is what makes "centralized log collection" happen for free: a log
    line becomes an ``Event`` like any domain signal, so it flows to every
    sink in ``OBSERVABILITY_SINKS`` — stdout, sqlite, webhook, otlp, and the
    ``postgres`` / ``mongodb`` sinks a deployment can opt into.
    """

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_OBS_LOGGER_PREFIX):
            return                        # never feed the pipe back into itself
        try:
            from . import observability as obs
            obs.event(
                "app.log", level=record.levelname.lower(),
                logger=record.name, message=record.getMessage(),
                module=record.module, line=record.lineno,
                exc_info=self.format(record) if record.exc_info else None,
            )
        except Exception:                # a logging handler must never raise
            pass


_MARKER = "_kd_structured_handler"          # tags handlers this module owns


def configure_logging(settings=None) -> None:
    """(Re)configure the root logger. Safe to call more than once — each call
    replaces only the handlers a *previous* call installed (tagged with
    :data:`_MARKER`), leaving anything else (pytest's log capture, a
    supervisor's own handler, …) untouched. ``app.main`` calls this again from
    the FastAPI startup event because uvicorn installs its own handlers after
    import time, and this needs to win that race."""
    if settings is None:
        from .config import get_settings
        settings = get_settings()

    level = getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO)
    fmt = (settings.log_format or "json").lower()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.addFilter(CorrelationFilter())
    stream_handler.setFormatter(
        TextFormatter() if fmt == "text" else
        JsonFormatter(service=settings.observability_service_name,
                     environment=settings.environment))

    bridge_level = getattr(logging, (settings.log_bridge_level or "WARNING").upper(),
                           logging.WARNING)
    bridge_handler = ObservabilityBridgeHandler(level=bridge_level)

    for h in (stream_handler, bridge_handler):
        setattr(h, _MARKER, True)

    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not getattr(h, _MARKER, False)]
    root.handlers.extend([stream_handler, bridge_handler])
    root.setLevel(level)

    # uvicorn installs its own handlers directly on these loggers with
    # propagate=False; strip that so access/error logs go through the same
    # structured pipeline instead of uvicorn's colourised text.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
