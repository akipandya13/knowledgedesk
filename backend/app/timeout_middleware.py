"""A hard ceiling on how long any one request may take.

Without this, a handler wedged on a slow dependency (a stuck socket, a runaway
query) holds a worker forever. ``asyncio.wait_for`` bounds it: on expiry the
client gets a clean ``504`` with the request id, and the event is counted so a
pattern of timeouts is visible in metrics.

Streaming endpoints (SSE) are exempt by path prefix — their response is
*meant* to stay open — via ``REQUEST_TIMEOUT_EXEMPT_PREFIXES``. Set
``REQUEST_TIMEOUT_SECONDS=0`` to disable entirely.
"""
from __future__ import annotations

import asyncio
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import get_settings

log = logging.getLogger("knowledgedesk.timeout")


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        limit = s.request_timeout_seconds
        path = request.url.path
        exempt = [p.strip() for p in (s.request_timeout_exempt_prefixes or "").split(",") if p.strip()]
        if limit <= 0 or any(path.startswith(p) for p in exempt) or not path.startswith("/api/"):
            return await call_next(request)
        try:
            return await asyncio.wait_for(call_next(request), timeout=limit)
        except asyncio.TimeoutError:
            rid = request.scope.get("kd_request_id", "")
            log.warning("request timeout after %ss: %s %s", limit, request.method, path)
            try:
                from . import observability as obs
                obs.count("http.server.timeouts", route=path, help="Requests exceeding REQUEST_TIMEOUT_SECONDS")
                obs.event("http.request.timeout", level="error", method=request.method,
                          path=path, timeout_seconds=limit)
            except Exception:                    # pragma: no cover
                pass
            return JSONResponse(status_code=504,
                                content={"detail": "Request timed out", "request_id": rid})
