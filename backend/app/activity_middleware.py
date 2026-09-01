"""One activity-log row per authenticated API call — the request firehose.

``get_principal`` stashes a light identity dict on the ASGI scope
(``scope["kd_actor"]``); after the response this middleware turns it into an
:class:`app.database.ActivityLog` row. Anonymous requests, health/metrics,
static assets, CORS pre-flight and token refresh are skipped. Everything is
best-effort — a logging failure must never affect the response.

Semantic events (``session.start``, ``document.retrieved``, exports, …) are
recorded explicitly by handlers via :func:`app.services.activity.record`; those
carry ``target_type`` / ``target_id`` this middleware cannot infer.
"""
from __future__ import annotations

import logging
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .config import get_settings
from .database import SessionLocal
from .request_context import client_ip
from .services import activity

log = logging.getLogger("knowledgedesk.activity")

_ID_SEG = re.compile(r"/\d+(?=/|$)")
_SKIP_EXACT = {"/api/health", "/api/auth/refresh", "/api/me/activity"}
_SKIP_PREFIX = ("/api/observability/metrics",)
# Admin control-plane surfaces — a write here is tracked as `admin`, not `write`,
# so "administrative activity" is a first-class filter.
_ADMIN_PREFIX = ("/api/admin/", "/api/access/", "/api/users", "/api/connectors",
                 "/api/sso/", "/api/observability/")


def _category(method: str, path: str) -> str:
    base = activity.category_for_method(method)
    if base == "write" and path.startswith(_ADMIN_PREFIX):
        return "admin"
    return base


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return _ID_SEG.sub("/:id", request.url.path)


def _skip(request: Request) -> bool:
    if request.method == "OPTIONS":
        return True
    path = request.url.path
    if not path.startswith("/api/"):
        return True
    if path in _SKIP_EXACT or path.startswith(_SKIP_PREFIX):
        return True
    return False


class ActivityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Capture edge metadata now — the RequestContext / Observability
        # context vars are torn down by the time call_next returns to us.
        ip = client_ip(request)
        ua = request.headers.get("user-agent", "")
        rid = request.headers.get("x-request-id", "")
        response = await call_next(request)
        try:
            s = get_settings()
            if not (s.activity_log_enabled and s.activity_log_requests):
                return response
            if _skip(request):
                return response
            actor = request.scope.get("kd_actor")
            if not actor:
                return response
            route = _route_template(request)
            ak_meta = ({"api_key_id": actor["api_key_id"],
                        "api_key_name": actor.get("api_key_name", "")}
                       if actor.get("api_key_id") is not None else None)
            db = SessionLocal()
            try:
                activity.record(
                    db, action=f"{request.method.lower()}:{route}",
                    category=_category(request.method, request.url.path),
                    user_id=actor.get("user_id"), actor_email=actor.get("email", ""),
                    actor_role=actor.get("role", ""), tenant_id=actor.get("tenant_id"),
                    method=request.method, route=route,
                    status=response.status_code, meta=ak_meta,
                    ip=ip, user_agent=ua, request_id=rid)
            finally:
                db.close()
        except Exception:                                # pragma: no cover — defensive
            log.exception("activity middleware failed")
        return response
