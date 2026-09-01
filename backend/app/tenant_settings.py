"""Effective per-tenant RAG/model settings."""
from __future__ import annotations

from typing import Any

from .config import get_settings
from .crypto import decrypt_secrets
from .database import Document, ModelConnector, SessionLocal, Tenant
from .model_catalog import MODEL_PROFILES, profile_defaults


def as_bool(value: Any) -> bool:
    """Parse booleans safely from JSON/form/env-style values.

    The previous implementation used bool(value), so the string "false" became
    True. That could leave reranking enabled after selecting the demo profile and
    trigger a Hugging Face CrossEncoder download on the first question.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}
    return False


def _normalize_settings(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    if "reranker_enabled" in out:
        out["reranker_enabled"] = as_bool(out.get("reranker_enabled"))
    # In laptop-safe mode, reranking must be explicitly enabled by environment.
    # This prevents a stale tenant setting from silently downloading/loading a
    # CrossEncoder on a 16 GB MacBook demo.
    if get_settings().laptop_safe_mode and not get_settings().allow_reranker_models:
        out["reranker_enabled"] = False
        if out.get("model_profile") in ("demo_fast", "extractive_zero_llm"):
            out["reranker_model"] = ""
            out["rerank_top_k"] = 0
    return out


def _base_defaults() -> dict[str, Any]:
    s = get_settings()
    return {
        "model_profile": s.model_profile,
        "embedding_provider": s.embedding_provider,
        "embedding_model": s.embedding_model,
        "reranker_enabled": s.reranker_enabled,
        "reranker_model": s.reranker_model,
        "rerank_top_k": s.rerank_top_k,
        "llm_provider": s.llm_provider,
        "llm_model": s.llm_model,
        "openai_model": s.openai_model,
        "retrieval_top_k": s.retrieval_top_k,
        "retrieval_score_threshold": s.retrieval_score_threshold,
        "retrieval_max_context_chars": s.retrieval_max_context_chars,
        "llm_temperature": s.llm_temperature,
        "llm_max_tokens": s.llm_max_tokens,
        "answer_language": s.answer_language,
    }


def effective_settings(tenant: Tenant | None) -> dict[str, Any]:
    """Global defaults + selected profile + tenant overrides."""
    base = _base_defaults()
    overrides = dict((tenant.settings_json or {}) if tenant else {})
    profile_key = overrides.get("model_profile") or base.get("model_profile")
    profile = profile_defaults(profile_key)
    merged = {**base, **profile, **overrides}
    merged["model_profile"] = profile_key if profile_key in MODEL_PROFILES else merged.get("model_profile", "custom")
    return _normalize_settings(merged)


def embedding_fingerprint(settings: dict[str, Any]) -> str:
    return f"{settings.get('embedding_provider','local')}:{settings.get('embedding_model','default')}"


# ── Model connectors ────────────────────────────────────────────────

def _connector_overrides(conn: ModelConnector, kind: str) -> dict[str, Any]:
    """Translate a ModelConnector row into runtime-config keys.

    `kind` is "llm" or "embedding"; keys are namespaced so a single resolved
    dict can carry both an LLM and an embedding connector at once.
    """
    cfg = dict(conn.config_json or {})
    sec = decrypt_secrets(conn.secret_encrypted, resolve=True)  # resolve ${provider:...} refs at runtime
    if kind == "llm":
        out: dict[str, Any] = {
            "llm_provider": conn.provider,
            "llm_model": conn.model_id or "",
            "llm_connector_name": conn.name,
        }
        if conn.provider == "openai_compatible":
            out["openai_model"] = conn.model_id or ""
            if cfg.get("base_url"):
                out["openai_base_url"] = cfg["base_url"]
            if sec.get("api_key"):
                out["openai_api_key"] = sec["api_key"]
        if conn.provider == "ollama" and cfg.get("base_url"):
            out["ollama_url"] = cfg["base_url"]
        if conn.provider == "bedrock":
            out["aws_region"] = cfg.get("region", "")
            out["aws_access_key_id"] = sec.get("aws_access_key_id", "")
            out["aws_secret_access_key"] = sec.get("aws_secret_access_key", "")
            out["aws_session_token"] = sec.get("aws_session_token", "")
        if conn.provider == "azure_foundry":
            out["azure_endpoint"] = cfg.get("endpoint", "")
            out["azure_deployment"] = cfg.get("deployment", "")
            out["azure_api_version"] = cfg.get("api_version", "")
            out["azure_api_key"] = sec.get("api_key", "")
        for k_src, k_dst in (("temperature", "llm_temperature"),
                             ("max_tokens", "llm_max_tokens"),
                             ("timeout_seconds", "llm_timeout_seconds")):
            if cfg.get(k_src) not in (None, ""):
                out[k_dst] = cfg[k_src]
        return out

    # embedding
    out = {
        "embedding_provider": conn.provider,
        "embedding_model": conn.model_id or "",
        "embedding_connector_name": conn.name,
    }
    if cfg.get("dimensions") not in (None, ""):
        out["embedding_dimensions"] = int(cfg["dimensions"])
    if conn.provider == "bedrock":
        out["embedding_region"] = cfg.get("region", "")
        out["embedding_aws_access_key_id"] = sec.get("aws_access_key_id", "")
        out["embedding_aws_secret_access_key"] = sec.get("aws_secret_access_key", "")
        out["embedding_aws_session_token"] = sec.get("aws_session_token", "")
    if conn.provider == "azure_foundry":
        out["embedding_endpoint"] = cfg.get("endpoint", "")
        out["embedding_deployment"] = cfg.get("deployment", "")
        out["embedding_api_version"] = cfg.get("api_version", "")
        out["embedding_api_key"] = sec.get("api_key", "")
    if conn.provider in ("openai_compatible", "ollama") and cfg.get("base_url"):
        out["embedding_base_url"] = cfg["base_url"]
    if conn.provider == "openai_compatible" and sec.get("api_key"):
        out["embedding_api_key"] = sec["api_key"]
    return out


#: Public alias — used by the admin router's connector "test" endpoint.
connector_overrides = _connector_overrides


def resolve_model_config(tenant: Tenant | None, db=None) -> dict[str, Any]:
    """effective_settings + any selected LLM/embedding connector overrides.

    The returned dict is a drop-in replacement for effective_settings() at every
    call site: when no connector is selected it is byte-for-byte the same.
    """
    cfg = effective_settings(tenant)
    if not tenant:
        return cfg

    owns_session = db is None
    db = db or SessionLocal()
    try:
        for kind in ("llm", "embedding"):
            cid = cfg.get(f"{kind}_connector_id")
            if not cid:
                continue
            conn = db.get(ModelConnector, int(cid))
            if not conn or conn.tenant_id != tenant.id or not conn.is_active:
                continue
            cfg.update(_connector_overrides(conn, kind))
    finally:
        if owns_session:
            db.close()
    return cfg


def embedding_locked(tenant: Tenant | None, db) -> bool:
    """True once the tenant has at least one indexed document — changing the
    embedding model after that would orphan every stored vector."""
    if not tenant:
        return False
    return db.query(Document).filter(
        Document.tenant_id == tenant.id,
        Document.status == "ready",
    ).count() > 0
