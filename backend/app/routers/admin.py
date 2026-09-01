"""Admin & analytics.

Tenant-scoped analytics: any authenticated member of the tenant can read
stats; settings changes require tenant_admin.

Platform admin (superadmin only): tenant lifecycle, platform-wide audit log,
cross-tenant stats. Superadmin has NO access to tenant document content.
"""
from __future__ import annotations

import csv
import datetime as dt
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func

import secrets as _secrets

from ..auth import (Principal, get_db, require, require_superadmin, tenant_ctx)
from ..rbac import Permission
from ..config import get_settings
from ..crypto import decrypt_secrets, encrypt_secrets
from ..database import (Document, ModelConnector, QueryLog,
                        ROLE_TENANT_ADMIN, TENANT_STATUS_ACTIVE,
                        TENANT_STATUS_SUSPENDED, Tenant, User, new_api_key)
from .. import authn
from .. import security
from ..services import activity as activity_svc
from ..services import tenants as tenants_svc
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
def stats(tenant=Depends(tenant_ctx(Permission.INSIGHTS_READ)), db=Depends(get_db)):
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
def recent_queries(limit: int = 50, tenant=Depends(tenant_ctx(Permission.INSIGHTS_READ)),
                   db=Depends(get_db)):
    rows = (db.query(QueryLog).filter(QueryLog.tenant_id == tenant.id)
            .order_by(QueryLog.created_at.desc()).limit(min(limit, 200)).all())
    return [{
        "id": r.id, "question": r.question, "mode": r.mode,
        "confidence": round(r.confidence or 0, 3), "latency_ms": r.latency_ms,
        "feedback": r.feedback,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@router.get("/gaps")
def knowledge_gaps(limit: int = 50, tenant=Depends(tenant_ctx(Permission.INSIGHTS_READ)),
                   db=Depends(get_db)):
    rows = (db.query(QueryLog)
            .filter(QueryLog.tenant_id == tenant.id, QueryLog.mode == "not_found")
            .order_by(QueryLog.created_at.desc()).limit(min(limit, 200)).all())
    return [{"question": r.question,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


class TenantSettingsUpdate(BaseModel):
    settings: dict


@router.get("/model-catalog")
def model_catalog(principal: Principal = Depends(require(Permission.MODEL_CONNECTOR_MANAGE))):
    """Dropdown options for tenant-admin model selection."""
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
def list_connectors(principal=Depends(require(Permission.MODEL_CONNECTOR_MANAGE)), db=Depends(get_db)):
    tenant = principal.tenant
    if not tenant:
        raise HTTPException(400, "Tenant context required")
    rows = (db.query(ModelConnector)
            .filter(ModelConnector.tenant_id == tenant.id)
            .order_by(ModelConnector.kind, ModelConnector.name).all())
    return [_connector_public(c) for c in rows]


@router.post("/model-connectors")
def create_connector(req: ConnectorCreate, principal=Depends(require(Permission.MODEL_CONNECTOR_MANAGE)),
                     db=Depends(get_db)):
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
    audit.record(db, action="tenant.model_connector_created", principal=principal,
                 tenant_id=tenant.id, target_type="model_connector", target_id=conn.id,
                 detail=f"{req.kind}:{req.provider}:{conn.model_id}")
    return _connector_public(conn)


@router.put("/model-connectors/{cid}")
def update_connector(cid: int, req: ConnectorUpdate, principal=Depends(require(Permission.MODEL_CONNECTOR_MANAGE)),
                     db=Depends(get_db)):
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

    before = {"name": conn.name, "model_id": conn.model_id,
              "config": dict(conn.config_json or {}), "is_active": bool(conn.is_active)}
    if req.name is not None:
        conn.name = req.name.strip() or conn.name
    if req.model_id is not None:
        conn.model_id = req.model_id.strip()
    if req.config is not None:
        conn.config_json = req.config or {}
    if req.is_active is not None:
        conn.is_active = req.is_active
    secret_rotated = False
    if req.secrets is not None:
        current = decrypt_secrets(conn.secret_encrypted)
        for k, v in req.secrets.items():
            if v == "":
                current.pop(k, None)
                secret_rotated = True
            elif v is not None:
                current[k] = v
                secret_rotated = True
        conn.secret_encrypted = encrypt_secrets(current)

    db.merge(conn)
    db.commit()
    after = {"name": conn.name, "model_id": conn.model_id,
             "config": dict(conn.config_json or {}), "is_active": bool(conn.is_active)}
    changed = audit.diff(before, after)
    if secret_rotated:
        changed["secrets"] = ["***", "***"]
    audit.record(db, action="tenant.model_connector_updated", principal=principal,
                 tenant_id=tenant.id, target_type="model_connector",
                 target_id=conn.id, changes=changed or None)
    return _connector_public(conn)


@router.delete("/model-connectors/{cid}")
def delete_connector(cid: int, principal=Depends(require(Permission.MODEL_CONNECTOR_MANAGE)), db=Depends(get_db)):
    tenant = principal.tenant
    conn = db.get(ModelConnector, cid)
    if not conn or not tenant or conn.tenant_id != tenant.id:
        raise HTTPException(404, "Connector not found")
    llm_sel, emb_sel = _tenant_selection(tenant)
    if str(conn.id) in (llm_sel, emb_sel):
        raise HTTPException(409, "Connector is currently selected in Settings. Switch to another "
                                 "connector first, then delete this one.")
    name = conn.name
    db.delete(conn)
    db.commit()
    audit.record(db, action="tenant.model_connector_deleted", principal=principal,
                 tenant_id=tenant.id, target_type="model_connector", target_id=cid,
                 detail=name)
    return {"deleted": cid}


@router.post("/model-connectors/{cid}/test")
async def test_connector(cid: int, principal=Depends(require(Permission.MODEL_CONNECTOR_MANAGE)), db=Depends(get_db)):
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
                            principal: Principal = Depends(require(Permission.SETTINGS_WRITE)),
                            db=Depends(get_db)):
    """Workspace admin or service key can change per-tenant RAG/model settings."""
    tenant = principal.tenant

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

    prev_settings = dict(tenant.settings_json or {})
    merged = dict(prev_settings)
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
    changed = audit.diff(prev_settings, merged)
    audit.record(db, action="tenant.model_settings_changed", principal=principal,
                 tenant_id=tenant.id, target_type="workspace_settings",
                 target_id=tenant.id, changes=changed or None,
                 detail="" if changed else "no effective change")
    return {"settings": merged, "effective": effective_settings(tenant), "note": safe_note}


@router.get("/config")
def effective_config(tenant=Depends(tenant_ctx(Permission.SETTINGS_READ)), db=Depends(get_db)):
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
def enterprise_readiness(tenant=Depends(tenant_ctx(Permission.SETTINGS_READ)), db=Depends(get_db)):
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


# ── Governance: audit trail & user activity ─────────────────────────
# Read side of app.services.audit (tamper-evident) and app.services.activity
# (behavioural). Query builders + hash-chain verification live in those
# services; these routes only parse params, gate on a permission and shape the
# response (JSON, or CSV for a compliance hand-off).

def _parse_ts(value: str | None):
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, f"Invalid timestamp: {value!r} (use ISO-8601)") from exc


def _csv_response(rows: list[dict], columns: list[str], filename: str) -> PlainTextResponse:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({c: _flat(r.get(c)) for c in columns})
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _flat(v):
    if isinstance(v, (dict, list)):
        import json
        return json.dumps(v, separators=(",", ":"), sort_keys=True)
    return "" if v is None else v


_AUDIT_CSV_COLS = ["id", "seq", "created_at", "actor", "actor_role", "action",
                   "target_type", "target_id", "ip", "detail", "entry_hash"]
_ACTIVITY_CSV_COLS = ["id", "created_at", "actor", "actor_role", "action",
                      "category", "target_type", "target_id", "method", "route",
                      "status", "ip"]


@router.get("/audit")
def tenant_audit(limit: int = 100,
                 action: str | None = None,
                 action_prefix: str | None = Query(None, alias="prefix"),
                 actor: str | None = None,
                 target_type: str | None = None,
                 target_id: str | None = None,
                 since: str | None = None, until: str | None = None,
                 before_id: int | None = None,
                 fmt: str = Query("json", alias="format"),
                 principal: Principal = Depends(require(Permission.AUDIT_READ)),
                 db=Depends(get_db)):
    """Filtered, newest-first slice of this workspace's audit trail.

    ``format=csv`` streams the same rows for a compliance hand-off (and is itself
    recorded as an ``export.audit`` activity event). Page with ``before_id``.
    """
    rows = audit.list_entries(
        db, tenant_id=principal.tenant.id, action=action, action_prefix=action_prefix,
        actor=actor, target_type=target_type, target_id=target_id,
        since=_parse_ts(since), until=_parse_ts(until), before_id=before_id,
        limit=limit)
    out = [audit.serialize(r) for r in rows]
    if fmt == "csv":
        activity_svc.record(db, action="export.audit", category="export",
                            principal=principal, target_type="audit_log",
                            meta={"rows": len(out), "filters": {
                                "action": action, "prefix": action_prefix,
                                "actor": actor, "since": since, "until": until}})
        audit.record(db, action="audit.exported", principal=principal,
                     target_type="audit_log", detail=f"{len(out)} rows (csv)")
        return _csv_response(out, _AUDIT_CSV_COLS, "audit-log.csv")
    return out


@router.get("/audit/verify")
def tenant_audit_verify(principal: Principal = Depends(require(Permission.AUDIT_READ)),
                        db=Depends(get_db)):
    """Recompute the workspace's hash chain and report integrity."""
    return audit.verify_chain(db, tenant_id=principal.tenant.id)


@router.get("/audit/history")
def tenant_audit_history(target_type: str, target_id: str, limit: int = 100,
                         principal: Principal = Depends(require(Permission.AUDIT_READ)),
                         db=Depends(get_db)):
    """Tamper-evident data-modification history for one entity — every audit
    entry that names it as the target, newest first, each with its
    ``changes`` ({field: [old, new]}) where one was captured."""
    rows = audit.list_entries(db, tenant_id=principal.tenant.id,
                              target_type=target_type, target_id=target_id,
                              limit=limit)
    return [audit.serialize(r) for r in rows]


@router.get("/activity")
def tenant_activity(limit: int = 100,
                    user_id: int | None = None,
                    action: str | None = None,
                    action_prefix: str | None = Query(None, alias="prefix"),
                    category: str | None = None,
                    actor: str | None = None,
                    target_type: str | None = None,
                    target_id: str | None = None,
                    since: str | None = None, until: str | None = None,
                    before_id: int | None = None,
                    fmt: str = Query("json", alias="format"),
                    principal: Principal = Depends(require(Permission.ACTIVITY_READ)),
                    db=Depends(get_db)):
    """The behavioural stream for this workspace — who viewed / ran / exported
    what. Filter by ``user_id`` for a per-person timeline."""
    rows = activity_svc.list_entries(
        db, tenant_id=principal.tenant.id, user_id=user_id, action=action,
        action_prefix=action_prefix, category=category, actor=actor,
        target_type=target_type, target_id=target_id, since=_parse_ts(since),
        until=_parse_ts(until), before_id=before_id, limit=limit)
    out = [activity_svc.serialize(r) for r in rows]
    if fmt == "csv":
        activity_svc.record(db, action="export.activity", category="export",
                            principal=principal, target_type="activity_log",
                            meta={"rows": len(out), "user_id": user_id})
        audit.record(db, action="activity.exported", principal=principal,
                     target_type="activity_log", detail=f"{len(out)} rows (csv)")
        return _csv_response(out, _ACTIVITY_CSV_COLS, "activity-log.csv")
    return out


# ── Platform admin: tenant (organization) lifecycle — superadmin only ─
# Mechanics live in app.services.tenants; these routes parse input, gate on
# `tenant.manage` (superadmin) and record a platform-chain audit entry.

def _get_tenant_or_404(db, slug: str) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
    if not tenant:
        raise HTTPException(404, "Workspace not found")
    return tenant


class TenantCreate(BaseModel):
    slug: str
    name: str
    admin_email: str | None = None       # provision the first workspace admin
    admin_full_name: str = ""
    entitlements: list[str] = []


class TenantUpdate(BaseModel):
    name: str | None = None
    entitlements: list[str] | None = None


class TenantSuspend(BaseModel):
    reason: str = ""


@router.post("/tenants")
def create_tenant(req: TenantCreate, principal=Depends(require_superadmin),
                  db=Depends(get_db)):
    slug = req.slug.strip().lower().replace(" ", "-")
    if not slug:
        raise HTTPException(400, "slug is required")
    if db.query(Tenant).filter(Tenant.slug == slug).first():
        raise HTTPException(409, "Workspace slug already exists")

    bad = set(req.entitlements) - authn.KNOWN_ENTITLEMENTS
    if bad:
        raise HTTPException(400, f"Unknown entitlements: {sorted(bad)}")

    email = req.admin_email.strip().lower() if req.admin_email else None
    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(409, f"A user with email {email} already exists")

    settings_json = {"entitlements": sorted(set(req.entitlements))} if req.entitlements else {}
    tenant = Tenant(slug=slug, name=req.name.strip() or slug, api_key=new_api_key(),
                    settings_json=settings_json, status=TENANT_STATUS_ACTIVE)
    db.add(tenant)
    db.commit()

    admin_out = None
    if email:
        temp_pw = "Kd-" + _secrets.token_urlsafe(9)
        admin = User(email=email, full_name=(req.admin_full_name.strip() or email),
                     password_hash=security.hash_password(temp_pw),
                     role=ROLE_TENANT_ADMIN, tenant_id=tenant.id,
                     force_password_change=1)
        db.add(admin)
        db.commit()
        audit.record(db, action="user.created", principal=principal,
                     tenant_id=tenant.id, target_type="user", target_id=admin.id,
                     detail=f"{email} as tenant_admin (workspace bootstrap)")
        admin_out = {"email": email, "temporary_password": temp_pw,
                     "note": "Shown once — the admin must change it at first sign-in."}

    audit.record(db, action="tenant.created", principal=principal, tenant_id=None,
                 target_type="tenant", target_id=tenant.id, detail=slug,
                 meta={"entitlements": settings_json.get("entitlements", []),
                       "admin_provisioned": bool(admin_out)})
    return {"id": tenant.id, "slug": tenant.slug, "name": tenant.name,
            "api_key": tenant.api_key, "status": tenant.status, "admin": admin_out}


@router.get("/tenants")
def list_tenants(principal=Depends(require_superadmin), db=Depends(get_db)):
    out = []
    for t in db.query(Tenant).order_by(Tenant.created_at).all():
        out.append({
            "id": t.id, "slug": t.slug, "name": t.name, "api_key": t.api_key,
            "status": t.status or TENANT_STATUS_ACTIVE,
            "suspended_reason": t.suspended_reason or None,
            "users": db.query(User).filter(User.tenant_id == t.id).count(),
            "documents": db.query(Document).filter(Document.tenant_id == t.id).count(),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return out


@router.get("/tenants/{slug}")
def get_tenant(slug: str, principal=Depends(require_superadmin), db=Depends(get_db)):
    tenant = _get_tenant_or_404(db, slug)
    return tenants_svc.tenant_detail(db, tenant,
                                     entitlements=authn.tenant_entitlements(tenant))


@router.patch("/tenants/{slug}")
def update_tenant(slug: str, req: TenantUpdate, principal=Depends(require_superadmin),
                  db=Depends(get_db)):
    tenant = _get_tenant_or_404(db, slug)
    st = dict(tenant.settings_json or {})
    before = {"name": tenant.name,
              "entitlements": sorted(st.get("entitlements") or [])}
    if req.name is not None:
        tenant.name = req.name.strip() or tenant.name
    if req.entitlements is not None:
        bad = set(req.entitlements) - authn.KNOWN_ENTITLEMENTS
        if bad:
            raise HTTPException(400, f"Unknown entitlements: {sorted(bad)}")
        st["entitlements"] = sorted(set(req.entitlements))
        tenant.settings_json = st
    db.merge(tenant)
    db.commit()
    after = {"name": tenant.name,
             "entitlements": sorted((tenant.settings_json or {}).get("entitlements") or [])}
    audit.record(db, action="tenant.updated", principal=principal, tenant_id=None,
                 target_type="tenant", target_id=tenant.id,
                 changes=audit.diff(before, after) or None, detail=slug)
    return tenants_svc.tenant_detail(db, tenant,
                                     entitlements=authn.tenant_entitlements(tenant))


@router.post("/tenants/{slug}/suspend")
def suspend_tenant(slug: str, req: TenantSuspend, principal=Depends(require_superadmin),
                   db=Depends(get_db)):
    tenant = _get_tenant_or_404(db, slug)
    if tenant.status == TENANT_STATUS_SUSPENDED:
        return tenants_svc.tenant_detail(db, tenant,
                                         entitlements=authn.tenant_entitlements(tenant))
    revoked = tenants_svc.set_status(db, tenant, status=TENANT_STATUS_SUSPENDED,
                                     reason=req.reason)
    audit.record(db, action="tenant.suspended", principal=principal, tenant_id=None,
                 target_type="tenant", target_id=tenant.id, detail=slug,
                 changes={"status": [TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED]},
                 meta={"reason": req.reason or "", "sessions_revoked": revoked})
    return tenants_svc.tenant_detail(db, tenant,
                                     entitlements=authn.tenant_entitlements(tenant))


@router.post("/tenants/{slug}/reactivate")
def reactivate_tenant(slug: str, principal=Depends(require_superadmin), db=Depends(get_db)):
    tenant = _get_tenant_or_404(db, slug)
    if tenant.status == TENANT_STATUS_ACTIVE:
        return tenants_svc.tenant_detail(db, tenant,
                                         entitlements=authn.tenant_entitlements(tenant))
    tenants_svc.set_status(db, tenant, status=TENANT_STATUS_ACTIVE)
    audit.record(db, action="tenant.reactivated", principal=principal, tenant_id=None,
                 target_type="tenant", target_id=tenant.id, detail=slug,
                 changes={"status": [TENANT_STATUS_SUSPENDED, TENANT_STATUS_ACTIVE]})
    return tenants_svc.tenant_detail(db, tenant,
                                     entitlements=authn.tenant_entitlements(tenant))


@router.delete("/tenants/{slug}")
def delete_tenant(slug: str, principal=Depends(require_superadmin), db=Depends(get_db)):
    tenant = _get_tenant_or_404(db, slug)
    tid = tenant.id
    tally = tenants_svc.purge_tenant_data(db, tenant)
    audit.record(db, action="tenant.deleted", principal=principal, tenant_id=None,
                 target_type="tenant", target_id=tid, detail=slug,
                 meta={"rows_deleted": tally})
    return {"deleted": slug, "rows_deleted": tally}


# ── Platform-wide audit log (superadmin only) ────────────────────────

@router.get("/platform/audit")
def platform_audit(limit: int = 200,
                   action: str | None = None,
                   action_prefix: str | None = Query(None, alias="prefix"),
                   actor: str | None = None,
                   tenant_id: int | None = None,
                   target_type: str | None = None,
                   since: str | None = None, until: str | None = None,
                   before_id: int | None = None,
                   fmt: str = Query("json", alias="format"),
                   principal=Depends(require_superadmin), db=Depends(get_db)):
    """Audit trail across every workspace plus platform-level events."""
    rows = audit.list_entries(
        db, platform_all=(tenant_id is None), tenant_id=tenant_id, action=action,
        action_prefix=action_prefix, actor=actor, target_type=target_type,
        since=_parse_ts(since), until=_parse_ts(until), before_id=before_id,
        limit=limit)
    out = [audit.serialize(r) for r in rows]
    if fmt == "csv":
        return _csv_response(out, ["tenant_id", *_AUDIT_CSV_COLS], "platform-audit-log.csv")
    return out


@router.get("/platform/audit/verify")
def platform_audit_verify(tenant_id: int | None = None,
                          principal=Depends(require_superadmin), db=Depends(get_db)):
    """Verify one workspace's hash chain, or every chain when ``tenant_id`` is
    omitted."""
    return audit.verify_chain(db, platform_all=(tenant_id is None), tenant_id=tenant_id)


@router.get("/platform/activity")
def platform_activity(limit: int = 200,
                      tenant_id: int | None = None,
                      user_id: int | None = None,
                      action: str | None = None,
                      action_prefix: str | None = Query(None, alias="prefix"),
                      category: str | None = None,
                      actor: str | None = None,
                      since: str | None = None, until: str | None = None,
                      before_id: int | None = None,
                      fmt: str = Query("json", alias="format"),
                      principal=Depends(require_superadmin), db=Depends(get_db)):
    """The behavioural stream across every workspace."""
    rows = activity_svc.list_entries(
        db, platform_all=(tenant_id is None), tenant_id=tenant_id, user_id=user_id,
        action=action, action_prefix=action_prefix, category=category, actor=actor,
        since=_parse_ts(since), until=_parse_ts(until), before_id=before_id,
        limit=limit)
    out = [activity_svc.serialize(r) for r in rows]
    if fmt == "csv":
        return _csv_response(out, ["tenant_id", *_ACTIVITY_CSV_COLS], "platform-activity-log.csv")
    return out


@router.get("/platform/stats")
def platform_stats(principal=Depends(require_superadmin), db=Depends(get_db)):
    return {
        "tenants": db.query(Tenant).count(),
        "users": db.query(User).filter(User.role != "superadmin").count(),
        "documents": db.query(Document).count(),
        "queries_total": db.query(QueryLog).count(),
    }
