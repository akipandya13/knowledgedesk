"""Effective per-tenant RAG/model settings."""
from __future__ import annotations

from typing import Any

from .config import get_settings
from .database import Tenant
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
