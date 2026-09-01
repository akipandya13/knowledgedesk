"""Liveness, readiness and dependency health.

Three questions, three answers — the split an orchestrator (Kubernetes, ECS,
a load balancer) expects:

* **liveness**  — is the process itself healthy, or wedged and in need of a
  restart? Cheap, no I/O, no dependencies. ``GET /livez`` (alias ``/healthz``).
* **readiness** — can it serve traffic *right now*? Startup bootstrap finished
  and every *required* dependency is reachable. ``GET /readyz`` → 200 or 503.
* **dependency health** — per-backend status + how long the check took, for
  ``GET /api/health`` and the dashboard.

``llm`` is deliberately **not required** for readiness: when it is down the app
still serves grounded extractive answers, so it is a degradation, not an outage.
``db`` and ``qdrant`` are required.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import text

from . import observability as obs
from .config import get_settings
from .database import SessionLocal
from .observability.resources import resource_snapshot
from .services import llm, vectorstore

log = logging.getLogger("knowledgedesk.health")

_started = time.time()
_ready_since: float | None = None       # set by mark_ready() at end of startup


def mark_ready() -> None:
    global _ready_since
    _ready_since = time.time()


def bootstrap_done() -> bool:
    return _ready_since is not None


# ── individual dependency probes ──────────────────────────────────

def _check_db() -> tuple[str, str]:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return "ok", ""
    finally:
        db.close()


def _check_qdrant() -> tuple[str, str]:
    return ("ok", "") if vectorstore.healthy() else ("down", "unreachable")


async def _check_llm() -> tuple[str, str]:
    s = get_settings()
    if s.llm_provider == "none":
        return "disabled", "LLM_PROVIDER=none"
    ok = await llm.is_available()
    return ("ok", "") if ok else ("down", f"{s.llm_provider} unreachable")


_REQUIRED = {"db", "qdrant"}


async def check_dependencies() -> list[dict]:
    """Run every dependency probe, timing each, and emit the gauges/histograms."""
    out: list[dict] = []
    checks = [
        ("db", _check_db, False),
        ("qdrant", _check_qdrant, False),
        ("llm", _check_llm, True),
    ]
    for name, fn, is_async in checks:
        t0 = time.perf_counter()
        try:
            status, detail = (await fn()) if is_async else fn()
        except Exception as exc:                  # a probe must never raise
            status, detail = "down", str(exc)[:200]
        dt = time.perf_counter() - t0
        required = name in _REQUIRED
        out.append({"name": name, "status": status, "required": required,
                    "latency_ms": round(dt * 1000, 1), "detail": detail or None})
        try:
            obs.gauge("dependency.up", 1 if status == "ok" else 0, dependency=name,
                      help="1 = dependency reachable")
            obs.observe("dependency.check.seconds", dt, dependency=name,
                        help="Duration of a dependency health probe")
        except Exception:                         # pragma: no cover
            pass
    return out


def _is_ready(deps: list[dict]) -> bool:
    if not bootstrap_done():
        return False
    return all(d["status"] == "ok" for d in deps if d["required"])


# ── the three views ───────────────────────────────────────────────

def liveness() -> dict:
    return {"status": "alive", "uptime_seconds": round(time.time() - _started, 1)}


async def readiness() -> tuple[bool, dict]:
    deps = await check_dependencies()
    ready = _is_ready(deps)
    try:
        obs.gauge("app.ready", 1 if ready else 0, help="1 = ready to serve traffic")
    except Exception:                             # pragma: no cover
        pass
    return ready, {
        "ready": ready,
        "bootstrap_complete": bootstrap_done(),
        "uptime_seconds": round(time.time() - _started, 1),
        "dependencies": deps,
    }


async def health_report() -> dict:
    """The detailed, human/dashboard-facing view — /api/health."""
    ready, payload = await readiness()
    s = get_settings()
    by_name = {d["name"]: d for d in payload["dependencies"]}
    return {
        "app": "ok",
        "ready": ready,
        "environment": s.environment,
        # back-compat top-level keys (older dashboards/tests read these)
        "qdrant": by_name.get("qdrant", {}).get("status", "unknown"),
        "llm": by_name.get("llm", {}).get("status", "unknown"),
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model,
        "uptime_seconds": payload["uptime_seconds"],
        "bootstrap_complete": payload["bootstrap_complete"],
        "dependencies": payload["dependencies"],
        "resources": resource_snapshot(),
    }
