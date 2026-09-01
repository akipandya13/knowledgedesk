"""Failure recovery — reconcile state left inconsistent by a crash or restart.

A process that dies mid-work leaves rows that will never move on their own: a
document stuck in ``processing``, a connector sync stuck in ``running``. This
runs once at startup and closes them out with a clear reason, so the UI and the
metrics reflect reality instead of a spinner that never stops. It also prunes
expired one-shot state (idempotency keys, used/expired auth tokens, revoked
refresh tokens).

Idempotent and best-effort: safe to run on every boot, and a failure here never
blocks startup.
"""
from __future__ import annotations

import datetime as dt
import logging

from . import observability as obs
from .config import get_settings
from .database import (AuthToken, Document, IdempotencyKey, RefreshToken,
                       ConnectorSyncRun, utcnow)

log = logging.getLogger("knowledgedesk.recovery")

_INTERRUPTED = "Interrupted by a service restart"


def reconcile_on_startup(db) -> dict:
    s = get_settings()
    now = utcnow()
    stuck_before = now - dt.timedelta(minutes=s.recovery_stuck_minutes)
    tally: dict[str, int] = {}

    try:
        # 1. Documents wedged in 'processing' — the bytes are gone (not stored),
        #    so mark failed with a reason the admin can act on (re-upload).
        n = (db.query(Document)
             .filter(Document.status == "processing",
                     Document.created_at < stuck_before)
             .update({"status": "failed", "error": _INTERRUPTED},
                     synchronize_session=False))
        if n:
            tally["documents_failed"] = int(n)

        # 2. Connector sync runs wedged in 'running'.
        n = (db.query(ConnectorSyncRun)
             .filter(ConnectorSyncRun.status == "running",
                     ConnectorSyncRun.started_at < stuck_before)
             .update({"status": "failed", "detail": _INTERRUPTED,
                      "finished_at": now}, synchronize_session=False))
        if n:
            tally["sync_runs_failed"] = int(n)

        # 3. Prune expired one-shot / cache state.
        idem_before = now - dt.timedelta(hours=s.idempotency_ttl_hours)
        n = (db.query(IdempotencyKey)
             .filter(IdempotencyKey.created_at < idem_before)
             .delete(synchronize_session=False))
        if n:
            tally["idempotency_keys_pruned"] = int(n)

        n = (db.query(AuthToken)
             .filter((AuthToken.expires_at < now) | (AuthToken.used_at.isnot(None)))
             .delete(synchronize_session=False))
        if n:
            tally["auth_tokens_pruned"] = int(n)

        n = (db.query(RefreshToken)
             .filter((RefreshToken.expires_at < now) | (RefreshToken.revoked == 1))
             .delete(synchronize_session=False))
        if n:
            tally["refresh_tokens_pruned"] = int(n)

        db.commit()
    except Exception:                            # never block startup
        db.rollback()
        log.exception("startup reconciliation failed")
        return {"error": "reconciliation failed"}

    if tally:
        log.warning("startup reconciliation: %s", tally)
        try:
            obs.event("recovery.reconciled", **tally)
            for k, v in tally.items():
                obs.count("recovery.rows", kind=k, value=v)
        except Exception:                        # pragma: no cover
            pass
    return tally
