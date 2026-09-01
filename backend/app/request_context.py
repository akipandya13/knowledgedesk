"""Ambient per-request metadata for the governance layer.

The audit trail and the activity log both want the caller's IP, User-Agent and
the request id — but threading a ``Request`` object through 45 audit call sites
and the RAG service would be noise. Instead a single middleware captures those
three values into a context var at the edge, and ``audit.record`` /
``activity.record`` read them back with :func:`current`.

Design notes
  * contextvars are task- and thread-local, so this is safe under Starlette's
    sync threadpool and asyncio routes alike (same pattern as
    ``app.observability.context``).
  * The middleware is registered *outside* :class:`ObservabilityMiddleware` so
    its ``request_id`` falls back to the obs context when a handler reads it;
    both resolve to the same value within a request.
  * Everything here is best-effort. A missing value is an empty string, never an
    exception.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import get_settings

_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "kd_request_meta", default=None)


@dataclass(frozen=True)
class RequestMeta:
    ip: str = ""
    user_agent: str = ""
    request_id: str = ""


def client_ip(request: Request) -> str:
    """Best client IP. Honours the first hop of ``X-Forwarded-For`` when the app
    is deployed behind a trusted reverse proxy (Caddy); see
    ``TRUST_FORWARDED_FOR`` / docs/DEPLOYMENT_TLS.md."""
    if get_settings().trust_forwarded_for:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
        real = request.headers.get("x-real-ip", "")
        if real:
            return real.strip()
    return request.client.host if request.client else ""


def bind(*, ip: str = "", user_agent: str = "", request_id: str = "") -> None:
    _ctx.set({"ip": ip, "user_agent": user_agent[:400], "request_id": request_id})


def clear() -> None:
    _ctx.set(None)


def current() -> RequestMeta:
    """The current request's metadata, or an all-empty :class:`RequestMeta`
    outside a request (scripts, tests, background tasks)."""
    data = _ctx.get()
    if not data:
        return RequestMeta()
    rid = data.get("request_id") or ""
    if not rid:
        try:
            from .observability import context as _obs_ctx
            rid = _obs_ctx.request_id() or ""
        except Exception:                                # pragma: no cover
            rid = ""
    return RequestMeta(ip=data.get("ip", ""), user_agent=data.get("user_agent", ""),
                       request_id=rid)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Capture IP / User-Agent / request id for the duration of the request."""

    async def dispatch(self, request: Request, call_next):
        try:
            rid = (request.headers.get("x-request-id")
                   or request.scope.get("kd_request_id") or "")
            bind(ip=client_ip(request),
                 user_agent=request.headers.get("user-agent", ""),
                 request_id=rid)
        except Exception:                                # pragma: no cover
            clear()
        try:
            return await call_next(request)
        finally:
            clear()
