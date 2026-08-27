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
from ..database import AuditLog, Document, QueryLog, Tenant, User, new_api_key
from ..model_catalog import MODEL_SETTING_KEYS, SAFE_DEMO_OLLAMA_MODELS, catalog_payload, profile_defaults
from ..tenant_settings import effective_settings, as_bool
from ..services import vectorstore
from ..services import audit

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


@router.get("/model-catalog")
def model_catalog(principal=Depends(require_member)):
    """Dropdown options for tenant-admin model selection."""
    from ..auth import ROLE_SERVICE
    from ..database import ROLE_TENANT_ADMIN, ROLE_SUPERADMIN
    if principal.role not in (ROLE_TENANT_ADMIN, ROLE_SERVICE, ROLE_SUPERADMIN):
        raise HTTPException(403, "Workspace admin permission required")
    return catalog_payload()


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
    if s.laptop_safe_mode and not s.allow_large_ollama_models:
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
    cfg = effective_settings(tenant)
    ready_docs = db.query(Document).filter(Document.tenant_id == tenant.id,
                                          Document.status == "ready",
                                          Document.is_active == True).all()  # noqa: E712
    current_embedding = cfg.get("embedding_model", "")
    indexed_current = sum(1 for d in ready_docs if (d.embedding_model or "") == current_embedding)
    return {
        **cfg,
        "chunk_size": s.chunk_size, "chunk_overlap": s.chunk_overlap,
        "tenant_overrides": tenant.settings_json or {},
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
