"""Admin & analytics.

Tenant-scoped analytics: any authenticated member of the tenant can read
stats; settings changes require tenant_admin.

Platform admin (superadmin only): tenant lifecycle, platform-wide audit log,
cross-tenant stats. Superadmin has NO access to tenant document content.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func

from ..auth import (get_db, get_tenant, get_tenant_admin,
                    require_member, require_superadmin, get_principal)
from ..config import get_settings
from ..crypto import decrypt_secrets, encrypt_secrets
from ..database import (AuditLog, Document, ModelConnector, QueryLog, Tenant,
                        User, new_api_key)
from ..model_catalog import (CONNECTOR_PROVIDERS, MODEL_SETTING_KEYS,
                             SAFE_DEMO_OLLAMA_MODELS, catalog_payload, profile_defaults)
from ..tenant_settings import (effective_settings, embedding_locked,
                               resolve_model_config, connector_overrides, as_bool)
from ..services import vectorstore
from ..services import audit
from ..services import embeddings as embeddings_service
from ..services import llm as llm_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Tenant-scoped analytics (any authenticated member) ───────────────

@router.get("/stats")
def stats(tenant=Depends(get_tenant), db=Depends(get_db)):
    docs = db.query(Document).filter(Document.tenant_id == tenant.id)
    queries = db.query(QueryLog).filter(QueryLog.tenant_id == tenant.id)
    answered = queries.filter(QueryLog.mode != "not_found")
    helpful = queries.filter(QueryLog.feedback == 1).count()
    unhelpful = queries.filter(QueryLog.feedback == -1).count()
    return {
        "documents_total": docs.count(),
        "documents_ready": docs.filter(Document.status == "ready").count(),
        "documents_failed": docs.filter(Document.status == "failed").count(),
        "chunks_total": db.query(func.coalesce(func.sum(Document.chunk_count), 0))
                          .filter(Document.tenant_id == tenant.id).scalar(),
        "queries_total": queries.count(),
        "queries_answered": answered.count(),
        "knowledge_gaps": queries.filter(QueryLog.mode == "not_found").count(),
        "avg_latency_ms": int(db.query(func.coalesce(func.avg(QueryLog.latency_ms), 0))
                              .filter(QueryLog.tenant_id == tenant.id).scalar()),
        "feedback_helpful": helpful,
        "feedback_unhelpful": unhelpful,
    }


@router.get("/queries")
def recent_queries(limit: int = 50, tenant=Depends(get_tenant), db=Depends(get_db)):
    rows = (db.query(QueryLog).filter(QueryLog.tenant_id == tenant.id)
            .order_by(QueryLog.created_at.desc()).limit(min(limit, 200)).all())
    return [{
        "id": r.id, "question": r.question, "mode": r.mode,
        "confidence": round(r.confidence or 0, 3), "latency_ms": r.latency_ms,
        "feedback": r.feedback,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@router.get("/gaps")
def knowledge_gaps(limit: int = 50, tenant=Depends(get_tenant), db=Depends(get_db)):
    rows = (db.query(QueryLog)
            .filter(QueryLog.tenant_id == tenant.id, QueryLog.mode == "not_found")
            .order_by(QueryLog.created_at.desc()).limit(min(limit, 200)).all())
    return [{"question": r.question,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


class TenantSettingsUpdate(BaseModel):
    settings: dict


def _require_workspace_admin(principal) -> None:
    from ..auth import ROLE_SERVICE
    from ..database import ROLE_TENANT_ADMIN, ROLE_SUPERADMIN
    if principal.role not in (ROLE_TENANT_ADMIN, ROLE_SERVICE, ROLE_SUPERADMIN):
        raise HTTPException(403, "Workspace admin permission required")


@router.get("/model-catalog")
def model_catalog(principal=Depends(require_member)):
    """Dropdown options for tenant-admin model selection."""
    _require_workspace_admin(principal)
    return catalog_payload()


# ── Model connectors (per-workspace LLM / embedding backends) ────────

class ConnectorCreate(BaseModel):
    kind: str
    name: str
    provider: str
    model_id: str = ""
    config: dict = {}
    secrets: dict = {}


class ConnectorUpdate(BaseModel):
    name: str | None = None
    model_id: str | None = None
    config: dict | None = None
    secrets: dict | None = None          # only provided keys change; "" clears one
    is_active: bool | None = None


def _connector_public(c: ModelConnector) -> dict:
    sec = decrypt_secrets(c.secret_encrypted)
    return {
        "id": c.id, "kind": c.kind, "name": c.name, "provider": c.provider,
        "model_id": c.model_id, "config": c.config_json or {},
        "is_active": bool(c.is_active),
        "secret_fields_set": sorted(k for k, v in sec.items() if v),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _validate_connector(kind: str, provider: str) -> None:
    if kind not in ("llm", "embedding"):
        raise HTTPException(400, "kind must be 'llm' or 'embedding'")
    spec = CONNECTOR_PROVIDERS.get(provider)
    if not spec:
        raise HTTPException(400, f"Unknown provider '{provider}'. Allowed: {sorted(CONNECTOR_PROVIDERS)}")
    if kind not in spec["kinds"]:
        raise HTTPException(400, f"Provider '{provider}' does not support kind '{kind}'")


def _tenant_selection(tenant) -> tuple[str, str]:
    o = tenant.settings_json or {}
    return str(o.get("llm_connector_id") or ""), str(o.get("embedding_connector_id") or "")


@router.get("/model-connectors")
def list_connectors(principal=Depends(require_member), db=Depends(get_db)):
    _require_workspace_admin(principal)
    tenant = principal.tenant
    if not tenant:
        raise HTTPException(400, "Tenant context required")
    rows = (db.query(ModelConnector)
            .filter(ModelConnector.tenant_id == tenant.id)
            .order_by(ModelConnector.kind, ModelConnector.name).all())
    return [_connector_public(c) for c in rows]


@router.post("/model-connectors")
def create_connector(req: ConnectorCreate, principal=Depends(require_member),
                     db=Depends(get_db)):
    _require_workspace_admin(principal)
    tenant = principal.tenant
    if not tenant:
        raise HTTPException(400, "Tenant context required")
    _validate_connector(req.kind, req.provider)
    conn = ModelConnector(
        tenant_id=tenant.id, kind=req.kind, name=req.name.strip() or req.provider,
        provider=req.provider, model_id=req.model_id.strip(),
        config_json=req.config or {},
        secret_encrypted=encrypt_secrets({k: v for k, v in (req.secrets or {}).items() if v}),
    )
    db.add(conn)
    db.commit()
    audit.record(db, action="tenant.model_connector_created", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=tenant.id,
                 detail=f"{req.kind}:{req.provider}:{conn.model_id} (#{conn.id})")
    return _connector_public(conn)


@router.put("/model-connectors/{cid}")
def update_connector(cid: int, req: ConnectorUpdate, principal=Depends(require_member),
                     db=Depends(get_db)):
    _require_workspace_admin(principal)
    tenant = principal.tenant
    conn = db.get(ModelConnector, cid)
    if not conn or not tenant or conn.tenant_id != tenant.id:
        raise HTTPException(404, "Connector not found")

    _, emb_sel = _tenant_selection(tenant)
    is_locked_embedding = (conn.kind == "embedding" and emb_sel == str(conn.id)
                           and embedding_locked(tenant, db))
    if is_locked_embedding:
        cur_cfg = conn.config_json or {}
        model_changed = req.model_id is not None and req.model_id.strip() != (conn.model_id or "")
        dim_changed = (req.config is not None
                       and str(req.config.get("dimensions", "")) != str(cur_cfg.get("dimensions", "")))
        if model_changed or dim_changed:
            raise HTTPException(409, "This embedding connector is locked: the workspace already has indexed "
                                     "documents. You may rotate credentials but not change the model or dimensions.")

    if req.name is not None:
        conn.name = req.name.strip() or conn.name
    if req.model_id is not None:
        conn.model_id = req.model_id.strip()
    if req.config is not None:
        conn.config_json = req.config or {}
    if req.is_active is not None:
        conn.is_active = req.is_active
    if req.secrets is not None:
        current = decrypt_secrets(conn.secret_encrypted)
        for k, v in req.secrets.items():
            if v == "":
                current.pop(k, None)
            elif v is not None:
                current[k] = v
        conn.secret_encrypted = encrypt_secrets(current)

    db.merge(conn)
    db.commit()
    audit.record(db, action="tenant.model_connector_updated", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=tenant.id, detail=f"#{conn.id}")
    return _connector_public(conn)


@router.delete("/model-connectors/{cid}")
def delete_connector(cid: int, principal=Depends(require_member), db=Depends(get_db)):
    _require_workspace_admin(principal)
    tenant = principal.tenant
    conn = db.get(ModelConnector, cid)
    if not conn or not tenant or conn.tenant_id != tenant.id:
        raise HTTPException(404, "Connector not found")
    llm_sel, emb_sel = _tenant_selection(tenant)
    if str(conn.id) in (llm_sel, emb_sel):
        raise HTTPException(409, "Connector is currently selected in Settings. Switch to another "
                                 "connector first, then delete this one.")
    db.delete(conn)
    db.commit()
    audit.record(db, action="tenant.model_connector_deleted", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=tenant.id, detail=f"#{cid}")
    return {"deleted": cid}


@router.post("/model-connectors/{cid}/test")
async def test_connector(cid: int, principal=Depends(require_member), db=Depends(get_db)):
    _require_workspace_admin(principal)
    tenant = principal.tenant
    conn = db.get(ModelConnector, cid)
    if not conn or not tenant or conn.tenant_id != tenant.id:
        raise HTTPException(404, "Connector not found")
    overrides = connector_overrides(conn, conn.kind)
    try:
        if conn.kind == "llm":
            if conn.provider == "none":
                return {"ok": True, "detail": "Provider 'none' — extractive answers, nothing to test."}
            out = await llm_service.generate("You are a connectivity test.",
                                             "Reply with the single word OK.", runtime=overrides)
            return {"ok": True, "detail": (out or "")[:120]}
        vec = embeddings_service.embed_query("connectivity test",
                                             provider=overrides.get("embedding_provider"),
                                             model_name=overrides.get("embedding_model"),
                                             runtime=overrides)
        return {"ok": True, "detail": f"embedding dim {len(vec)}"}
    except Exception as e:  # noqa: BLE001 — surface any backend failure to the admin
        return {"ok": False, "detail": str(e)[:400]}


@router.put("/settings")
def update_tenant_settings(req: TenantSettingsUpdate,
                            principal=Depends(require_member),
                            db=Depends(get_db)):
    """Tenant_admin or service key can change per-tenant RAG/model settings."""
    from ..auth import ROLE_SERVICE
    from ..database import ROLE_TENANT_ADMIN, ROLE_SUPERADMIN
    if principal.role not in (ROLE_TENANT_ADMIN, ROLE_SERVICE, ROLE_SUPERADMIN):
        raise HTTPException(403, "Workspace admin permission required")
    tenant = principal.tenant
    if not tenant:
        raise HTTPException(400, "Tenant context required")

    bad = set(req.settings) - MODEL_SETTING_KEYS
    if bad:
        raise HTTPException(400, f"Unknown settings: {sorted(bad)}. Allowed: {sorted(MODEL_SETTING_KEYS)}")

    # Selecting a profile applies the profile defaults first; any explicit fields
    # in the same request override those defaults. This makes the dropdown useful
    # while still allowing advanced customization.
    incoming = dict(req.settings)

    # Embedding configuration is immutable once documents are indexed: changing
    # the embedding model would orphan every vector already stored in Qdrant.
    if embedding_locked(tenant, db):
        cur = effective_settings(tenant)
        def _changes(key):
            return key in incoming and str(incoming[key] or "") != str(cur.get(key) or "")
        if _changes("embedding_connector_id") or _changes("embedding_model") or _changes("embedding_provider"):
            raise HTTPException(409, "Embedding configuration is locked: this workspace already has "
                                     "indexed documents. Delete the tenant or re-index from scratch to "
                                     "change the embedding model.")

    merged = dict(tenant.settings_json or {})
    if incoming.get("model_profile"):
        merged.update(profile_defaults(incoming["model_profile"]))
    merged.update(incoming)

    # Basic type normalization from the browser form.
    for k in ("retrieval_top_k", "rerank_top_k", "retrieval_max_context_chars", "llm_max_tokens"):
        if k in merged and merged[k] not in (None, ""):
            merged[k] = int(merged[k])
    for k in ("retrieval_score_threshold", "llm_temperature"):
        if k in merged and merged[k] not in (None, ""):
            merged[k] = float(merged[k])
    if "reranker_enabled" in merged:
        merged["reranker_enabled"] = as_bool(merged["reranker_enabled"])

    # MacBook/demo safety: tenant admins can still see premium choices, but
    # this deployment will not persist settings that trigger large downloads or
    # missing Ollama model fallbacks unless the operator explicitly allows them.
    safe_note = None
    s = get_settings()
    # A selected model connector points at a remote/managed backend (Bedrock,
    # Azure, hosted endpoint) or an explicitly-configured local one — it does not
    # risk a multi-GB download on this host, so laptop-safe mode leaves it alone.
    uses_connector = bool(merged.get("llm_connector_id") or merged.get("embedding_connector_id"))
    if s.laptop_safe_mode and not s.allow_large_ollama_models and not uses_connector:
        unsafe_profile = merged.get("model_profile") not in ("demo_fast", "extractive_zero_llm")
        unsafe_llm = (merged.get("llm_provider", "ollama") == "ollama"
                      and merged.get("llm_model")
                      and merged.get("llm_model") not in SAFE_DEMO_OLLAMA_MODELS)
        if unsafe_profile or unsafe_llm:
            merged.update(profile_defaults("demo_fast"))
            merged["model_profile"] = "demo_fast"
            safe_note = "MacBook safe mode reset this tenant to Demo Fast / Laptop Safe. Set ALLOW_LARGE_OLLAMA_MODELS=true to persist larger Ollama models."

    if s.laptop_safe_mode and not s.allow_reranker_models:
        merged["reranker_enabled"] = False
        merged["reranker_model"] = ""
        merged["rerank_top_k"] = 0

    tenant.settings_json = merged
    db.merge(tenant)
    db.commit()
    audit.record(db, action="tenant.model_settings_changed", actor_email=principal.email,
                 actor_role=principal.role, tenant_id=tenant.id,
                 detail=str(incoming))
    return {"settings": merged, "effective": effective_settings(tenant), "note": safe_note}


@router.get("/config")
def effective_config(tenant=Depends(get_tenant), db=Depends(get_db)):
    s = get_settings()
    cfg = resolve_model_config(tenant, db)
    ready_docs = db.query(Document).filter(Document.tenant_id == tenant.id,
                                          Document.status == "ready",
                                          Document.is_active == True).all()  # noqa: E712
    current_embedding = cfg.get("embedding_model", "")
    indexed_current = sum(1 for d in ready_docs if (d.embedding_model or "") == current_embedding)

    def _summary(cid):
        conn = db.get(ModelConnector, int(cid)) if cid else None
        if not conn or conn.tenant_id != tenant.id:
            return None
        return {"id": conn.id, "name": conn.name, "provider": conn.provider,
                "model_id": conn.model_id, "kind": conn.kind}

    overrides = tenant.settings_json or {}
    locked = embedding_locked(tenant, db)
    return {
        **cfg,
        "chunk_size": s.chunk_size, "chunk_overlap": s.chunk_overlap,
        "tenant_overrides": overrides,
        "llm_connector": _summary(overrides.get("llm_connector_id")),
        "embedding_connector": _summary(overrides.get("embedding_connector_id")),
        "embedding_locked": locked,
        "embedding_locked_reason": (
            "This workspace has indexed documents; the embedding model is fixed to keep "
            "existing vectors valid." if locked else None),
        "embedding_locked_to": overrides.get("embedding_locked_to"),
        "index_status": {
            "ready_documents": len(ready_docs),
            "documents_indexed_for_current_embedding": indexed_current,
            "reindex_required": bool(ready_docs and indexed_current < len(ready_docs)),
            "current_embedding_model": current_embedding,
        },
    }


@router.get("/readiness")
def enterprise_readiness(tenant=Depends(get_tenant), db=Depends(get_db)):
    """Board/demo-friendly view of whether a tenant is ready for rollout."""
    docs = db.query(Document).filter(Document.tenant_id == tenant.id)
    queries = db.query(QueryLog).filter(QueryLog.tenant_id == tenant.id)
    ready = docs.filter(Document.status == "ready").count()
    total = docs.count()
    gaps = queries.filter(QueryLog.mode == "not_found").count()
    return {
        "tenant": tenant.slug,
        "rollout_stage": "demo-ready" if ready else "needs-documents",
        "checks": {
            "multi_tenant_isolation": "enabled",
            "local_llm_default": get_settings().llm_provider == "ollama",
            "citations": get_settings().answer_include_citations,
            "audit_log": "enabled",
            "bulk_zip_ingestion": "enabled",
            "drive_sharepoint_connectors": "configured" if (get_settings().gdrive_access_token or get_settings().msgraph_client_secret) else "stub-ready",
        },
        "document_status": {"total": total, "ready": ready, "failed": docs.filter(Document.status == "failed").count()},
        "usage": {"queries": queries.count(), "knowledge_gaps": gaps},
        "recommended_next_step": "Upload ZIP/Drive export and run 20 pilot questions" if ready else "Seed or upload documents",
    }


# ── Audit log (tenant-scoped) ────────────────────────────────────────

@router.get("/audit")
def tenant_audit(limit: int = 100, principal=Depends(require_member), db=Depends(get_db)):
    from ..database import ROLE_TENANT_ADMIN
    from ..auth import ROLE_SERVICE
    if principal.role not in (ROLE_TENANT_ADMIN, ROLE_SERVICE):
        raise HTTPException(403, "Workspace admin required")
    rows = (db.query(AuditLog)
            .filter(AuditLog.tenant_id == principal.tenant.id)
            .order_by(AuditLog.created_at.desc())
            .limit(min(limit, 500)).all())
    return [{"id": r.id, "actor": r.actor_email, "action": r.action,
             "detail": r.detail,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


# ── Platform admin: tenant lifecycle (superadmin only) ───────────────

class TenantCreate(BaseModel):
    slug: str
    name: str


@router.post("/tenants")
def create_tenant(req: TenantCreate,
                  principal=Depends(require_superadmin),
                  db=Depends(get_db)):
    slug = req.slug.strip().lower().replace(" ", "-")
    if db.query(Tenant).filter(Tenant.slug == slug).first():
        raise HTTPException(409, "Tenant slug already exists")
    tenant = Tenant(slug=slug, name=req.name.strip(), api_key=new_api_key())
    db.add(tenant)
    db.commit()
    audit.record(db, action="tenant.created", actor_email=principal.email,
                 actor_role=principal.role, detail=slug)
    return {"slug": tenant.slug, "name": tenant.name, "api_key": tenant.api_key,
            "id": tenant.id}


@router.get("/tenants")
def list_tenants(principal=Depends(require_superadmin), db=Depends(get_db)):
    tenants = db.query(Tenant).all()
    out = []
    for t in tenants:
        user_count = db.query(User).filter(User.tenant_id == t.id).count()
        doc_count = db.query(Document).filter(Document.tenant_id == t.id).count()
        out.append({
            "id": t.id, "slug": t.slug, "name": t.name,
            "api_key": t.api_key,
            "users": user_count,
            "documents": doc_count,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return out


@router.delete("/tenants/{slug}")
def delete_tenant(slug: str, principal=Depends(require_superadmin), db=Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    vectorstore.drop_tenant(tenant.slug)
    db.query(QueryLog).filter(QueryLog.tenant_id == tenant.id).delete()
    db.query(User).filter(User.tenant_id == tenant.id).delete()
    db.delete(tenant)
    db.commit()
    audit.record(db, action="tenant.deleted", actor_email=principal.email,
                 actor_role=principal.role, detail=slug)
    return {"deleted": slug}


# ── Platform-wide audit log (superadmin only) ────────────────────────

@router.get("/platform/audit")
def platform_audit(limit: int = 200, principal=Depends(require_superadmin),
                   db=Depends(get_db)):
    rows = (db.query(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(min(limit, 1000)).all())
    return [{"id": r.id, "tenant_id": r.tenant_id, "actor": r.actor_email,
             "role": r.actor_role, "action": r.action, "detail": r.detail,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


@router.get("/platform/stats")
def platform_stats(principal=Depends(require_superadmin), db=Depends(get_db)):
    return {
        "tenants": db.query(Tenant).count(),
        "users": db.query(User).filter(User.role != "superadmin").count(),
        "documents": db.query(Document).count(),
        "queries_total": db.query(QueryLog).count(),
    }
