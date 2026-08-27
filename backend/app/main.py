"""KnowledgeDesk v1 — application entrypoint."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .auth import get_db, get_tenant
from .config import get_settings
from .database import Document, SessionLocal, Tenant, User, init_db
from .routers import admin, connectors, documents, query
from .routers import auth_routes, users as users_router
from .services import llm, vectorstore
from .services.ingestion import ingest_document
from . import security
from .model_catalog import HEAVY_LOCAL_MODELS, LARGE_OLLAMA_MODELS, SAFE_DEMO_OLLAMA_MODELS, profile_defaults
from .tenant_settings import as_bool

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("knowledgedesk")

settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0",
              description="Semantic internal search — ask questions, get cited answers.")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"], expose_headers=["*"])

# ── Routers ─────────────────────────────────────────────────────────
app.include_router(auth_routes.router)
app.include_router(users_router.router)
app.include_router(documents.router)
app.include_router(query.router)
app.include_router(admin.router)
app.include_router(connectors.router)


def _bootstrap_db(db) -> None:
    """Create superadmin and demo tenant/users on first startup."""
    s = get_settings()

    # 1. Superadmin account
    superadmin = db.query(User).filter(User.email == s.superadmin_email).first()
    if not superadmin:
        superadmin = User(
            email=s.superadmin_email,
            full_name="Platform Administrator",
            password_hash=security.hash_password(s.superadmin_password),
            role="superadmin",
            tenant_id=None,
            force_password_change=1,
        )
        db.add(superadmin)
        db.commit()
        log.info("Superadmin created: %s (change password on first login)", s.superadmin_email)

    # 2. Demo tenant
    if s.demo_tenant_enabled:
        demo_tenant = db.query(Tenant).filter(Tenant.slug == "demo").first()
        if not demo_tenant:
            demo_tenant = Tenant(slug="demo", name="Demo Company",
                                 api_key=s.demo_tenant_api_key)
            db.add(demo_tenant)
            db.commit()
            log.info("Demo tenant created (API key: %s)", s.demo_tenant_api_key)

        # 3. Demo users (only when demo_users_enabled)
        if s.demo_users_enabled:
            demo_admin_email = "admin@demo.knowledgedesk.local"
            if not db.query(User).filter(User.email == demo_admin_email).first():
                db.add(User(
                    email=demo_admin_email, full_name="Demo Admin",
                    password_hash=security.hash_password("Demo-Admin123!"),
                    role="tenant_admin", tenant_id=demo_tenant.id,
                    force_password_change=0,
                ))
                db.commit()
                log.info("Demo tenant_admin: %s / Demo-Admin123!", demo_admin_email)

            demo_member_email = "employee@demo.knowledgedesk.local"
            if not db.query(User).filter(User.email == demo_member_email).first():
                db.add(User(
                    email=demo_member_email, full_name="Demo Employee",
                    password_hash=security.hash_password("Demo-User123!"),
                    role="member", tenant_id=demo_tenant.id,
                    force_password_change=0,
                ))
                db.commit()
                log.info("Demo member: %s / Demo-User123!", demo_member_email)


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


@app.on_event("startup")
def startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        _bootstrap_db(db)
        _enforce_safe_model_defaults(db)
    finally:
        db.close()
    log.info("%s ready — LLM=%s/%s, embeddings=%s", settings.app_name,
             settings.llm_provider, settings.llm_model, settings.embedding_provider)


@app.get("/api/health")
async def health():
    return {
        "app": "ok",
        "qdrant": "ok" if vectorstore.healthy() else "down",
        "llm": ("ok" if await llm.is_available()
                else ("disabled" if settings.llm_provider == "none" else "down")),
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "environment": settings.environment,
    }


@app.post("/api/demo/seed")
def seed_demo(background: BackgroundTasks, tenant=Depends(get_tenant),
              db=Depends(get_db)):
    """Load the bundled sample company documents into this tenant."""
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
                       status="queued", size_bytes=len(data))
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
