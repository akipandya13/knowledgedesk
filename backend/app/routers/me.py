"""Self-service governance — what the platform has recorded about *you*.

Any authenticated workspace principal can read their own activity trail (and
only their own — the filter is pinned to ``principal.user_id``). This is the
transparency counterpart to the admin-only activity explorer: a user can see
their own sessions, the documents their questions retrieved, and the admin
surfaces they opened.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException

from ..auth import Principal, get_db, get_principal
from ..services import activity as activity_svc

router = APIRouter(prefix="/api/me", tags=["me"])


def _parse_ts(value: str | None):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, f"Invalid timestamp: {value!r}") from exc


@router.get("/activity")
def my_activity(limit: int = 50,
                action_prefix: str | None = None,
                category: str | None = None,
                since: str | None = None, until: str | None = None,
                before_id: int | None = None,
                principal: Principal = Depends(get_principal),
                db=Depends(get_db)):
    """The caller's own activity trail. Open to every authenticated principal —
    including the platform administrator (who simply has no workspace rows) and
    API keys (no ``user_id``, so an empty list). It is *self*-scoped, not
    workspace content, so the "no workspace access" rule does not apply."""
    if principal.user_id is None:
        return []
    rows = activity_svc.list_entries(
        db,
        tenant_id=principal.tenant.id if principal.tenant else None,
        platform_all=principal.tenant is None,
        user_id=principal.user_id,
        action_prefix=action_prefix, category=category, since=_parse_ts(since),
        until=_parse_ts(until), before_id=before_id, limit=min(limit, 200))
    return [activity_svc.serialize(r) for r in rows]
