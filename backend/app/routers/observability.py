"""Read APIs for the observability data the platform collects.

  * /config            — which sinks are active, sample rate, drop count
  * /metrics            — JSON snapshot of the in-process registry
  * /events             — recent domain events (sqlite sink)
  * /traces/{id}        — spans for one request id (sqlite sink)

Tenant admins and service keys see only their workspace's slice (series /
events / spans labelled with another tenant are filtered out). Superadmin sees
everything. The Prometheus text endpoint is mounted separately at `/metrics`
(see app.main) for scrapers.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException

from .. import observability as obs
from ..auth import Principal, require
from ..database import ROLE_SUPERADMIN
from ..rbac import Permission

router = APIRouter(prefix="/api/observability", tags=["observability"])

_guard = require(Permission.OBSERVABILITY_READ, tenant_required=False)


def _scope(principal: Principal) -> str | None:
    """None → see everything (superadmin). Otherwise the caller's tenant slug."""
    if principal.role == ROLE_SUPERADMIN:
        return None
    return principal.tenant.slug if principal.tenant else "__none__"


@router.get("/config")
def observability_config(principal: Principal = Depends(_guard)) -> dict:
    return obs.config_view()


@router.get("/slo")
def observability_slo(principal: Principal = Depends(_guard)) -> dict:
    """Response-time targets vs. the current p50/p95, from the live registry."""
    from ..observability.slo import slo_report
    return slo_report()


@router.get("/metrics")
def metrics_snapshot(principal: Principal = Depends(_guard)) -> dict:
    snap = obs.snapshot()
    scope = _scope(principal)
    if scope is not None:
        for metric in snap.get("metrics", []):
            metric["series"] = [
                s for s in metric["series"]
                if s["labels"].get("tenant") in (None, scope)
            ]
    return snap


@router.get("/events")
def observability_events(kind: str | None = None, since_seconds: int | None = None,
                         limit: int = 200,
                         principal: Principal = Depends(_guard)) -> dict:
    store = obs.sink("sqlite")
    if store is None:
        raise HTTPException(409, "The 'sqlite' observability sink is not enabled")
    since = time.time() - since_seconds if since_seconds else None
    rows = store.query_events(tenant=_scope(principal), kind=kind, since=since, limit=limit)
    return {"events": rows, "count": len(rows)}


@router.get("/traces/{request_id}")
def observability_trace(request_id: str,
                        principal: Principal = Depends(_guard)) -> dict:
    store = obs.sink("sqlite")
    if store is None:
        raise HTTPException(409, "The 'sqlite' observability sink is not enabled")
    spans = store.query_trace(request_id, tenant=_scope(principal))
    if not spans:
        raise HTTPException(404, "No spans recorded for that request id")
    return {"request_id": request_id, "spans": spans}
