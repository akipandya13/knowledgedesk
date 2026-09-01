"""HTTP instrumentation middleware.

Per request: assign/propagate a request id (`X-Request-ID`), bind it plus the
matched route template into the observability context, time the request, and
record:

  * counter   ``http.server.requests``          {method, route, status_class}
  * histogram ``http.server.duration.seconds``  {method, route}
  * gauge     ``http.server.in_flight``
  * event     ``http.request``                  (level=error for 5xx)

Tenant/actor labels are attached to *domain* events and spans from inside
handler context (bound by ``get_principal``), not here — the auth identity is
not known until dependencies run.
"""
from __future__ import annotations

import re
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from . import context as _ctx
from . import count, event, gauge, observe

_ID_SEG = re.compile(r"/\d+(?=/|$)")


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    # Not matched (404) or middleware ran before routing populated scope.
    return _ID_SEG.sub("/:id", request.url.path)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or _ctx.new_id(8)
        # Also on the ASGI scope (shared with the Request the global exception
        # handler receives) — that handler runs in ServerErrorMiddleware,
        # *outside* every middleware here, after this dispatch's `finally` has
        # already torn down the contextvar.
        request.scope["kd_request_id"] = rid
        tokens = _ctx.bind(request_id=rid, route=request.url.path)
        gauge("http.server.in_flight", _inc())
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            dur = time.perf_counter() - t0
            route = _route_template(request)
            cls = f"{status // 100}xx"
            count("http.server.requests", method=request.method, route=route, status_class=cls,
                  help="HTTP requests handled")
            observe("http.server.duration.seconds", dur, method=request.method, route=route,
                    help="HTTP request duration")
            gauge("http.server.in_flight", _dec())
            event("http.request", level="error" if status >= 500 else "info",
                  method=request.method, route=route, status=status,
                  duration_ms=round(dur * 1000, 1))
            _ctx.unbind(tokens)
            _ctx.reset_all()          # tenant/actor bound by get_principal, etc.


_inflight = 0


def _inc() -> int:
    global _inflight
    _inflight += 1
    return _inflight


def _dec() -> int:
    global _inflight
    _inflight = max(0, _inflight - 1)
    return _inflight
