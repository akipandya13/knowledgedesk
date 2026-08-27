"""Audit trail — who did what, when.

Written for every security-relevant event: logins (success and failure),
user lifecycle, document deletion, settings changes, tenant lifecycle.
Read by tenant admins (own tenant) and the platform operator (all).
"""
from __future__ import annotations

import logging

from ..database import AuditLog

log = logging.getLogger("knowledgedesk.audit")


def record(db, *, action: str, actor_email: str = "", actor_role: str = "",
           tenant_id: int | None = None, detail: str = "") -> None:
    try:
        db.add(AuditLog(action=action, actor_email=actor_email,
                        actor_role=actor_role, tenant_id=tenant_id,
                        detail=detail[:2000]))
        db.commit()
    except Exception:                                     # noqa: BLE001
        db.rollback()
        log.exception("Audit write failed for action=%s", action)
