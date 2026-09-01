"""User activity tracking — the behavioural stream.

Where the audit log (app.services.audit) is the tamper-evident record of
*effected security changes*, the activity log answers "what has this person been
doing on the platform" — including **reads**: sessions started, documents
retrieved through a query, admin surfaces opened, data exported.

It is deliberately cheaper than the audit log: no hash chain, retention-bounded
(``ACTIVITY_RETENTION_DAYS``, trimmed by scripts/purge_logs.py), and every write
is best-effort. Two producers:

* :class:`app.activity_middleware.ActivityMiddleware` — one row per authenticated
  API call (the firehose; toggle with ``ACTIVITY_LOG_REQUESTS``).
* explicit :func:`record` calls at semantically interesting points, which add
  ``target_type`` / ``target_id`` and a friendly ``action`` the firehose can't
  infer.

Read surfaces: ``GET /api/admin/activity`` (``activity.read``),
``GET /api/me/activity`` (any principal, own rows only), and the platform
variant for superadmin.
"""
from __future__ import annotations

import logging

from ..config import get_settings
from ..database import ActivityLog
from ..request_context import current as _req

log = logging.getLogger("knowledgedesk.activity")

# method → default category for the request firehose
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def enabled() -> bool:
    return bool(get_settings().activity_log_enabled)


def record(db, *, action: str, category: str = "", principal=None,
           user_id: int | None = None, actor_email: str = "", actor_role: str = "",
           tenant_id: int | None = None, target_type: str = "",
           target_id: "str | int" = "", method: str = "", route: str = "",
           status: int = 0, meta: dict | None = None,
           ip: str | None = None, user_agent: str | None = None,
           request_id: str | None = None) -> None:
    """Append one activity row. Best-effort; never raises.

    ``ip`` / ``user_agent`` / ``request_id`` fall back to the ambient request
    context; pass them explicitly from a middleware that runs after the context
    has already been torn down.
    """
    if not enabled():
        return
    try:
        meta = dict(meta or {})
        if principal is not None:
            actor_email = actor_email or getattr(principal, "actor_label", "") \
                or getattr(principal, "email", "")
            actor_role = actor_role or getattr(principal, "role", "")
            if user_id is None:
                user_id = getattr(principal, "user_id", None)
            if tenant_id is None and getattr(principal, "tenant", None) is not None:
                tenant_id = principal.tenant.id
            akid = getattr(principal, "api_key_id", None)
            if akid is not None:
                meta.setdefault("api_key_id", akid)
                meta.setdefault("api_key_name", getattr(principal, "api_key_name", ""))
        rc = _req()
        db.add(ActivityLog(
            tenant_id=tenant_id, user_id=user_id, actor_email=actor_email or "",
            actor_role=actor_role or "", action=action, category=category or "",
            target_type=target_type or "",
            target_id=str(target_id) if target_id not in (None, "") else "",
            method=method or "", route=route or "", status=int(status or 0),
            ip=(rc.ip if ip is None else ip),
            user_agent=(rc.user_agent if user_agent is None else user_agent)[:400],
            request_id=(rc.request_id if request_id is None else request_id),
            meta=meta or {}))
        db.commit()
    except Exception:                                     # noqa: BLE001
        db.rollback()
        log.exception("Activity write failed for action=%s", action)


def category_for_method(method: str) -> str:
    return "write" if method.upper() in _WRITE_METHODS else "read"


# ── Read side ──────────────────────────────────────────────────────

def serialize(row: ActivityLog) -> dict:
    return {
        "id": row.id, "tenant_id": row.tenant_id, "user_id": row.user_id,
        "actor": row.actor_email, "actor_role": row.actor_role,
        "action": row.action, "category": row.category or None,
        "target_type": row.target_type or None, "target_id": row.target_id or None,
        "method": row.method or None, "route": row.route or None,
        "status": row.status or None, "ip": row.ip or None,
        "request_id": row.request_id or None, "meta": row.meta or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_entries(db, *, tenant_id: int | None = None, platform_all: bool = False,
                 user_id: int | None = None, action: str | None = None,
                 action_prefix: str | None = None, category: str | None = None,
                 actor: str | None = None, target_type: str | None = None,
                 target_id: str | None = None, since=None, until=None,
                 before_id: int | None = None, limit: int = 100):
    q = db.query(ActivityLog)
    if not platform_all:
        q = q.filter(ActivityLog.tenant_id == tenant_id)
    if user_id is not None:
        q = q.filter(ActivityLog.user_id == user_id)
    if action:
        q = q.filter(ActivityLog.action == action)
    if action_prefix:
        q = q.filter(ActivityLog.action.like(f"{action_prefix}%"))
    if category:
        q = q.filter(ActivityLog.category == category)
    if actor:
        q = q.filter(ActivityLog.actor_email.like(f"%{actor}%"))
    if target_type:
        q = q.filter(ActivityLog.target_type == target_type)
    if target_id:
        q = q.filter(ActivityLog.target_id == str(target_id))
    if since is not None:
        q = q.filter(ActivityLog.created_at >= since)
    if until is not None:
        q = q.filter(ActivityLog.created_at <= until)
    if before_id is not None:
        q = q.filter(ActivityLog.id < before_id)
    return (q.order_by(ActivityLog.id.desc())
            .limit(max(1, min(limit, 1000))).all())


def purge(db, *, older_than) -> int:
    """Delete activity rows created before ``older_than``. Returns the count."""
    n = (db.query(ActivityLog)
         .filter(ActivityLog.created_at < older_than)
         .delete(synchronize_session=False))
    db.commit()
    return int(n or 0)
