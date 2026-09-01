"""KnowledgeDesk v1 — application entrypoint."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import observability as obs
from .auth import get_db, tenant_ctx
from .config import get_settings
from .database import (DOC_SCOPE_TENANT, Document, SessionLocal, Tenant, User,
                       init_db)
from . import health
from . import recovery
from .observability import context as obs_ctx
from .observability.middleware import ObservabilityMiddleware
from .observability.resources import resource_metrics_loop
from .activity_middleware import ActivityMiddleware
from .idempotency import IdempotencyMiddleware
from .timeout_middleware import RequestTimeoutMiddleware
from .logging_setup import configure_logging
from .request_context import RequestContextMiddleware
from .rbac import Permission
from .secret_resolver import available_providers, resolve_secret
from .routers import access, admin, connectors, documents, query, sso
from .routers import auth_routes, me as me_router, observability as observability_router, users as users_router
from .services.ingestion import ingest_document
from . import security
from .model_catalog import HEAVY_LOCAL_MODELS, LARGE_OLLAMA_MODELS, SAFE_DEMO_OLLAMA_MODELS, profile_defaults
from .tenant_settings import as_bool

settings = get_settings()
configure_logging(settings)
log = logging.getLogger("knowledgedesk")

app = FastAPI(title=settings.app_name, version="1.0.0",
              description="Semantic internal search — ask questions, get cited answers.")

_cors = [o.strip() for o in (settings.cors_allow_origins or "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_cors or ["*"], allow_methods=["*"],
                   allow_headers=["*"], expose_headers=["*"],
                   allow_credentials=settings.auth_refresh_cookie)
# Observability is initialised before the middleware records anything.
obs.setup(settings)
app.add_middleware(ObservabilityMiddleware)
# Governance: capture request metadata (IP / UA / request id) for the audit &
# activity logs, then record one activity row per authenticated API call.
app.add_middleware(RequestContextMiddleware)
app.add_middleware(ActivityMiddleware)
# Resilience: replay retried mutating requests that carry an Idempotency-Key,
# then bound every request with a hard timeout (added last → outermost).
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(RequestTimeoutMiddleware)

# ── Edge hardening (added last → evaluated first) ───────────────────
_hosts = [h.strip() for h in (settings.trusted_hosts or "*").split(",") if h.strip()]
if _hosts and _hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_hosts)
if settings.force_https_redirect:
    # Normally the reverse proxy (Caddy) does this; enable only when the app is
    # directly internet-facing. Relies on uvicorn --proxy-headers.
    app.add_middleware(HTTPSRedirectMiddleware)

# ── Routers ─────────────────────────────────────────────────────────
app.include_router(auth_routes.router)
app.include_router(users_router.router)
app.include_router(documents.router)
app.include_router(query.router)
app.include_router(admin.router)
app.include_router(connectors.router)
app.include_router(observability_router.router)
app.include_router(access.router)
app.include_router(sso.router)
app.include_router(me_router.router)


# ── Error logs ────────────────────────────────────────────────────────
# The one place an unhandled exception is turned into: a structured log line
# (stack trace + correlation ids, via logging_setup), an observability error
# event + counter (so it hits every configured sink), and a response that
# never leaks internals to the caller.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # A handler for the bare Exception class runs in Starlette's outermost
    # ServerErrorMiddleware — *outside* every middleware here, after
    # ObservabilityMiddleware's `finally` has already cleared the correlation
    # contextvar. Both survive on the ASGI scope (the same Request), so
    # re-bind them for the duration of the log line + event below.
    actor_info = request.scope.get("kd_actor") or {}
    rid = (request.scope.get("kd_request_id") or obs_ctx.request_id()
          or request.headers.get("x-request-id", ""))
    tokens = obs_ctx.bind(request_id=rid, actor=actor_info.get("email"),
                         route=request.url.path)
    try:
        log.error("Unhandled exception on %s %s", request.method, request.url.path,
                 exc_info=exc)
        obs.count("app.errors", type=type(exc).__name__,
                 help="Unhandled exceptions, by type")
        obs.event("app.error", level="error", method=request.method,
                 path=request.url.path, error_type=type(exc).__name__,
                 error=str(exc)[:500], tenant_id=actor_info.get("tenant_id"))
    finally:
        obs_ctx.unbind(tokens)
    return JSONResponse(status_code=500,
                        content={"detail": "Internal server error", "request_id": rid})


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics(authorization: str = Header(default="")):
    """Prometheus text exposition. Enabled only with the `prometheus` sink;
    optionally protected by OBS_PROMETHEUS_TOKEN."""
    if "prometheus" not in obs.active_sinks():
        raise HTTPException(404, "Prometheus sink not enabled")
    token = settings.obs_prometheus_token
    if token and authorization != f"Bearer {token}":
        raise HTTPException(401, "metrics token required")
    return PlainTextResponse(obs.render_prometheus(), media_type="text/plain; version=0.0.4")


def _bootstrap_db(db) -> None:
    """Create superadmin and demo tenant/users on first startup."""
    s = get_settings()

    # 1. Superadmin account
    superadmin = db.query(User).filter(User.email == s.superadmin_email).first()
    if not superadmin:
        superadmin = User(
            email=s.superadmin_email,
            full_name="Platform Administrator",
            password_hash=security.hash_password(resolve_secret(s.superadmin_password)),
            role="superadmin",
            tenant_id=None,
            force_password_change=1 if s.superadmin_force_password_change else 0,
        )
        db.add(superadmin)
        db.commit()
        log.info("Superadmin created: %s", s.superadmin_email)

    # 2. Demo tenant
    if s.demo_tenant_enabled:
        demo_tenant = db.query(Tenant).filter(Tenant.slug == "demo").first()
        if not demo_tenant:
            demo_tenant = Tenant(slug="demo", name="Demo Company",
                                 api_key=s.demo_tenant_api_key)
            db.add(demo_tenant)
            db.commit()
            log.info("Demo tenant created (API key: %s)", s.demo_tenant_api_key)

        # 3. Demo users — one per workspace role (only when demo_users_enabled)
        if s.demo_users_enabled:
            if not db.query(User).filter(User.email == s.demo_admin_email).first():
                db.add(User(
                    email=s.demo_admin_email, full_name="Demo Admin",
                    password_hash=security.hash_password(resolve_secret(s.demo_admin_password)),
                    role="tenant_admin", tenant_id=demo_tenant.id,
                    force_password_change=0,
                ))
                db.commit()
                log.info("Demo tenant_admin: %s", s.demo_admin_email)

            if not db.query(User).filter(User.email == s.demo_member_email).first():
                db.add(User(
                    email=s.demo_member_email, full_name="Demo Member",
                    password_hash=security.hash_password(resolve_secret(s.demo_member_password)),
                    role="member", tenant_id=demo_tenant.id,
                    force_password_change=0,
                ))
                db.commit()
                log.info("Demo member: %s", s.demo_member_email)


def _enforce_safe_model_defaults(db) -> None:
    """Prevent existing Docker volumes from silently loading slow local models.

    Two safety fixes happen here:
    1. Premium Qwen 4B embedding/reranker choices are reset unless heavy models
       are explicitly enabled.
    2. On laptop-safe deployments, stale tenant settings such as
       {"reranker_enabled": "false"} or old enterprise profiles cannot trigger
       a BGE CrossEncoder download during the first question.
    """
    s = get_settings()
    if not s.auto_downgrade_blocked_models:
        return

    heavy = set(HEAVY_LOCAL_MODELS)
    safe = {**profile_defaults("demo_fast"), "model_profile": "demo_fast"}
    changed = 0
    reranker_disabled = 0
    for tenant in db.query(Tenant).all():
        cfg = dict(tenant.settings_json or {})

        # A tenant that has picked an explicit model connector is managing its
        # own backend (Bedrock / Azure / hosted / configured local). Laptop-safe
        # downgrades target accidental multi-GB local downloads and do not apply.
        if cfg.get("llm_connector_id") or cfg.get("embedding_connector_id"):
            continue

        # Existing premium settings from earlier builds should not survive on a
        # MacBook/demo setup unless explicitly allowed. In laptop-safe mode we
        # also downgrade larger Ollama models such as gemma3:12b because the
        # image only pre-pulls gemma3:4b by default and missing models caused
        # the confusing "language model unavailable" fallback.
        unsafe_hf = (not s.allow_heavy_local_models
                     and (cfg.get("embedding_model") in heavy or cfg.get("reranker_model") in heavy))
        unsafe_llm = (s.laptop_safe_mode and not s.allow_large_ollama_models
                      and cfg.get("llm_provider", "ollama") == "ollama"
                      and cfg.get("llm_model")
                      and cfg.get("llm_model") not in SAFE_DEMO_OLLAMA_MODELS)
        unsafe_profile = (s.laptop_safe_mode and not s.allow_large_ollama_models
                          and cfg.get("model_profile") not in (None, "", "demo_fast", "extractive_zero_llm"))
        if unsafe_hf or unsafe_llm or unsafe_profile:
            tenant.settings_json = dict(safe)
            db.merge(tenant)
            changed += 1
            continue

        # Guard against the bool("false") bug and against stale enterprise
        # reranker settings on 16 GB laptop deployments.
        if s.laptop_safe_mode and not s.allow_reranker_models:
            normalized_enabled = as_bool(cfg.get("reranker_enabled"))
            if normalized_enabled or cfg.get("reranker_model"):
                cfg["reranker_enabled"] = False
                if cfg.get("model_profile") in ("demo_fast", "extractive_zero_llm", None, ""):
                    cfg["reranker_model"] = ""
                    cfg["rerank_top_k"] = 0
                tenant.settings_json = cfg
                db.merge(tenant)
                reranker_disabled += 1

    if changed or reranker_disabled:
        db.commit()
    if changed:
        log.warning("Reset %s tenant(s) to demo_fast because MacBook/demo safe mode blocked heavy HF models, large Ollama models, or unsafe profiles.", changed)
    if reranker_disabled:
        log.warning("Disabled stale tenant reranker settings for %s tenant(s) because laptop-safe mode is enabled.", reranker_disabled)


_health_task: asyncio.Task | None = None
_resource_task: asyncio.Task | None = None


async def _health_probe_loop(period: int) -> None:
    """Refresh dependency-up gauges + check latency on a timer so monitoring
    sees outages even when no one is using the app."""
    from .observability.slo import slo_report
    while True:
        try:
            await health.check_dependencies()
            slo_report(emit=True)              # refresh slo.* gauges for alerting
        except Exception:                       # never let the probe die
            log.exception("observability health probe failed")
        await asyncio.sleep(period)


@app.on_event("startup")
def startup() -> None:
    global _health_task, _resource_task
    # Re-apply after uvicorn installs its own logging config (which happens
    # after this module is imported) — last configuration wins.
    configure_logging(settings)
    init_db()
    db = SessionLocal()
    try:
        _bootstrap_db(db)
        _enforce_safe_model_defaults(db)
        recovery.reconcile_on_startup(db)     # close out work interrupted by a restart
    finally:
        db.close()
    if obs.is_enabled():
        try:
            loop = asyncio.get_running_loop()
            period = settings.observability_health_probe_seconds
            if period > 0:
                _health_task = loop.create_task(_health_probe_loop(period))
            rperiod = settings.obs_resource_metrics_seconds
            if rperiod > 0:
                _resource_task = loop.create_task(resource_metrics_loop(rperiod))
        except RuntimeError:
            log.warning("observability: no running loop at startup; background probes disabled")
    health.mark_ready()
    log.info("%s ready — LLM=%s/%s, embeddings=%s | secret providers: %s",
             settings.app_name, settings.llm_provider, settings.llm_model,
             settings.embedding_provider, ", ".join(available_providers()))


@app.on_event("shutdown")
def shutdown() -> None:
    for task in (_health_task, _resource_task):
        if task:
            task.cancel()
    obs.shutdown()
    from . import http_client
    http_client.close()


@app.on_event("shutdown")
async def _close_async_resources() -> None:
    from . import http_client
    await http_client.aclose()


# ── Health / liveness / readiness probes ─────────────────────────────
# Split the way an orchestrator expects. /livez is cheap (no I/O); /readyz
# gates traffic on required dependencies + startup bootstrap; /api/health is
# the detailed dashboard view. See docs/functionality/37-health-check.md.
@app.get("/livez", tags=["health"])
@app.get("/healthz", include_in_schema=False)
def livez():
    return health.liveness()


@app.get("/readyz", tags=["health"])
async def readyz():
    ready, payload = await health.readiness()
    if not ready:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/api/health", tags=["health"])
async def api_health():
    return await health.health_report()


@app.post("/api/demo/seed")
def seed_demo(background: BackgroundTasks,
              tenant=Depends(tenant_ctx(Permission.DOC_WRITE_TENANT)),
              db=Depends(get_db)):
    """Load the bundled sample company documents into this tenant (company-wide)."""
    sample_dir = Path("/app/sample_docs")
    if not sample_dir.exists():
        return {"queued": 0, "note": "sample_docs directory not mounted"}
    queued = 0
    existing = {d.filename for d in
                db.query(Document).filter(Document.tenant_id == tenant.id).all()}
    for path in sorted(sample_dir.iterdir()):
        if not path.is_file() or path.name in existing:
            continue
        data = path.read_bytes()
        doc = Document(tenant_id=tenant.id, filename=path.name, source="seed",
                       status="queued", size_bytes=len(data),
                       scope=DOC_SCOPE_TENANT, owner_user_id=None)
        db.add(doc)
        db.commit()
        background.add_task(ingest_document, doc.id, tenant.slug, path.name, data)
        queued += 1
    return {"queued": queued}


# ── Static UI ────────────────────────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# HTML5 history-mode fallback for the single-page frontend.
# This makes /ask, /documents, /insights, /users, etc. work when opened
# directly, refreshed, or shared as links, while all /api/* routes above keep
# their normal behaviour.
@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
