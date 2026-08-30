"""Observability facade — the only surface application code should import.

    from app import observability as obs

    obs.count("rag.answers", mode="llm", tenant="acme")
    obs.observe("rag.stage.seconds", 0.42, stage="vector_search", tenant="acme")
    obs.gauge("llm.backend.up", 1, provider="ollama")
    obs.event("question.answered", mode="llm", latency_ms=812, confidence=0.7)

    with obs.span("rag.answer") as sp:
        sp.set(mode="llm")
        ...

Design:
  * Vendor-neutral. No third-party client is a hard dependency.
  * Pluggable. Where signals go is chosen by `OBSERVABILITY_SINKS`; add a sink
    class + one line in `sinks/__init__.py` (see that module's docstring).
  * Safe. When disabled, every call is a cheap no-op. When enabled, a failing
    sink can never raise into the request path.
  * Self-sufficient. An always-on in-process registry backs `/metrics` and the
    JSON snapshot even with no sinks configured.
"""
from __future__ import annotations

import logging
import random
import threading
import time
import traceback

from . import context as _ctx
from .dispatcher import Dispatcher
from .models import Event, MetricKind, Sample, Span
from .registry import Registry
from .sinks import build_sinks

log = logging.getLogger("knowledgedesk.observability")

_lock = threading.Lock()
_enabled = False
_registry = Registry()
_dispatcher: Dispatcher | None = None
_sinks: list = []
_sample_rate = 1.0
_service = "knowledgedesk"
_init_done = False


# ── lifecycle ──────────────────────────────────────────────────────

def setup(settings) -> None:
    """Build sinks from settings. Idempotent; call from app startup."""
    global _enabled, _dispatcher, _sinks, _sample_rate, _service, _init_done, _registry
    with _lock:
        _init_done = True
        _enabled = bool(getattr(settings, "observability_enabled", True))
        _service = getattr(settings, "observability_service_name", "knowledgedesk")
        _sample_rate = float(getattr(settings, "observability_sample_traces", 1.0))
        _registry = Registry(max_series=int(getattr(settings, "observability_max_series", 2000)))
        names = [n for n in getattr(settings, "observability_sinks", "stdout").split(",") if n.strip()]
        _sinks = build_sinks(settings, names) if _enabled else []
        if _dispatcher:
            _dispatcher.close()
        _dispatcher = Dispatcher(_registry, _sinks)
        log.info("observability: enabled=%s sinks=%s", _enabled,
                 [s.name for s in _sinks] or ["<none>"])


def _ensure() -> None:
    global _init_done, _dispatcher
    if _init_done and _dispatcher is not None:
        return
    # Facade used before app startup, or after shutdown() (scripts, tests).
    try:
        from ..config import get_settings
        setup(get_settings())
    except Exception:
        _init_done = True
        if _dispatcher is None:
            _dispatcher = Dispatcher(_registry, [])


def shutdown() -> None:
    """Flush and close sinks. The facade stays usable — a later call re-inits."""
    global _dispatcher, _init_done
    with _lock:
        if _dispatcher:
            _dispatcher.close()
        _dispatcher = None
        _init_done = False


def flush() -> None:
    if _dispatcher:
        _dispatcher.flush()


def is_enabled() -> bool:
    return _enabled


def active_sinks() -> list[str]:
    return [s.name for s in _sinks]


def sink(name: str):
    """Return the live sink instance by name (used by the query router)."""
    for s in _sinks:
        if s.name == name:
            return s
    return None


def config_view() -> dict:
    return {
        "enabled": _enabled,
        "service": _service,
        "sinks": active_sinks(),
        "trace_sample_rate": _sample_rate,
        "queue_dropped": _dispatcher.dropped if _dispatcher else 0,
    }


# ── metrics ────────────────────────────────────────────────────────

def _labels(kw: dict) -> dict[str, str]:
    snap = _ctx.current()
    if "tenant" not in kw and snap.tenant:
        kw = {**kw, "tenant": snap.tenant}
    return {k: str(v) for k, v in kw.items() if v is not None}


def _dispatch():
    _ensure()
    return _dispatcher


def count(name: str, value: float = 1.0, *, help: str = "", **labels) -> None:
    if not _enabled:
        return
    d = _dispatch()
    if d is not None:
        d.metric(Sample(name, MetricKind.COUNTER, value, _labels(labels)), help_=help)


def gauge(name: str, value: float, *, help: str = "", **labels) -> None:
    if not _enabled:
        return
    d = _dispatch()
    if d is not None:
        d.metric(Sample(name, MetricKind.GAUGE, value, _labels(labels)), help_=help)


def observe(name: str, value: float, *, help: str = "", buckets=None, **labels) -> None:
    """Record a histogram observation (seconds, bytes, counts …)."""
    if not _enabled:
        return
    d = _dispatch()
    if d is not None:
        d.metric(Sample(name, MetricKind.HISTOGRAM, value, _labels(labels)),
                 help_=help, buckets=buckets)


class _Timer:
    def __init__(self, name: str, labels: dict):
        self._name, self._labels = name, labels

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        observe(self._name, time.perf_counter() - self._t0, **self._labels)
        return False


def timer(name: str, **labels) -> _Timer:
    """`with obs.timer("x.seconds", stage="parse"): ...` → histogram of duration."""
    return _Timer(name, labels)


# ── events ─────────────────────────────────────────────────────────

def event(kind: str, *, level: str = "info", **fields) -> None:
    if not _enabled:
        return
    d = _dispatch()
    if d is None:
        return
    snap = _ctx.current()
    tenant = fields.pop("tenant", None) or snap.tenant
    actor = fields.pop("actor", None) or snap.actor
    d.event(Event(
        kind=kind, fields=fields, level=level,
        request_id=snap.request_id, trace_id=snap.request_id,
        tenant=tenant, actor=actor, route=snap.route,
    ))


# ── spans ──────────────────────────────────────────────────────────

class _ActiveSpan:
    __slots__ = ("_span", "_tok", "_noop")

    def __init__(self, span: Span | None):
        self._span = span
        self._tok = None
        self._noop = span is None

    def set(self, **attrs) -> "_ActiveSpan":
        if not self._noop:
            self._span.attributes.update({k: v for k, v in attrs.items()})
        return self

    def add_event(self, name: str, **attrs) -> None:
        if not self._noop:
            self._span.events.append({"ts": time.time(), "name": name, "attrs": attrs})

    def __enter__(self) -> "_ActiveSpan":
        if not self._noop:
            self._tok = _ctx.push_span(self._span.span_id)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._noop:
            return False
        if exc_type is not None:
            self._span.status = "error"
            self._span.attributes.setdefault("error.type", getattr(exc_type, "__name__", "error"))
            self._span.attributes.setdefault("error.message", str(exc)[:500])
        self._span.end = time.perf_counter()
        self._span.duration_ms = (self._span.end - self._span.start) * 1000.0
        _ctx.pop_span(self._tok)
        d = _dispatcher
        if d is not None:
            d.span(self._span)
        # a span also feeds a duration histogram, so metrics work without a trace sink
        observe("span.duration.seconds", self._span.duration_ms / 1000.0,
                span=self._span.name, status=self._span.status)
        return False


def span(name: str, **attrs) -> _ActiveSpan:
    if not _enabled:
        return _ActiveSpan(None)
    if _dispatch() is None:
        return _ActiveSpan(None)
    if _sample_rate < 1.0 and random.random() > _sample_rate:
        return _ActiveSpan(None)
    snap = _ctx.current()
    trace_id = snap.request_id or _ctx.new_id(16)
    sp = Span(
        name=name, span_id=_ctx.new_id(8), trace_id=trace_id,
        parent_id=snap.span_id, request_id=snap.request_id,
        tenant=attrs.pop("tenant", None) or snap.tenant,
        attributes={k: v for k, v in attrs.items() if v is not None},
    )
    return _ActiveSpan(sp)


# ── context re-exports ─────────────────────────────────────────────

bind = _ctx.bind
unbind = _ctx.unbind
request_id = _ctx.request_id
current_context = _ctx.current


class bound:
    """`with obs.bound(tenant="acme", actor="u@x"): ...`"""

    def __init__(self, **fields):
        self._fields = fields
        self._tok = None

    def __enter__(self):
        self._tok = _ctx.bind(**self._fields)
        return self

    def __exit__(self, *exc):
        _ctx.unbind(self._tok or [])
        return False


# ── read surfaces (used by the router) ─────────────────────────────

def snapshot() -> dict:
    snap = _registry.snapshot()
    snap["service"] = _service
    snap["generated_at"] = time.time()
    snap["sinks"] = active_sinks()
    return snap


def render_prometheus() -> str:
    return _registry.render_prometheus()
