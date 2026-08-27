"""Optional cross-encoder reranking for retrieved chunks."""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from ..config import get_settings
from ..model_catalog import OPTIONAL_RERANKER_MODELS, model_warning

log = logging.getLogger("knowledgedesk.reranker")
_models: dict[str, object] = {}
_lock = threading.Lock()


class RerankerBlocked(RuntimeError):
    pass


def _guard_model(model_name: str) -> None:
    s = get_settings()
    if not model_name:
        raise RerankerBlocked("No reranker model selected.")
    optional_warning = OPTIONAL_RERANKER_MODELS.get(model_name)
    if optional_warning and not s.allow_reranker_models:
        raise RerankerBlocked(
            f"{optional_warning} Reranker skipped because ALLOW_RERANKER_MODELS is false."
        )
    warning = model_warning(model_name)
    if warning and not s.allow_heavy_local_models:
        raise RerankerBlocked(
            f"{warning} Reranker skipped because ALLOW_HEAVY_LOCAL_MODELS is false."
        )


def _model(model_name: str):
    _guard_model(model_name)
    s = get_settings()
    if s.hf_token and not os.environ.get("HF_TOKEN"):
        os.environ["HF_TOKEN"] = s.hf_token
    if model_name not in _models:
        with _lock:
            if model_name not in _models:
                from sentence_transformers import CrossEncoder
                try:
                    _models[model_name] = CrossEncoder(model_name, trust_remote_code=True)
                except TypeError:
                    _models[model_name] = CrossEncoder(model_name)
    return _models[model_name]


def rerank(question: str, hits: list[dict[str, Any]], model_name: str,
           top_k: int) -> list[dict[str, Any]]:
    """Return hits ordered by cross-encoder relevance.

    Reranking is an optional quality layer. If it is unavailable or blocked by
    demo-safe mode, vector search results are returned instead of breaking Q&A.
    """
    if not hits or not model_name:
        return hits[:top_k]
    try:
        pairs = [(question, h.get("text", "")) for h in hits]
        scores = _model(model_name).predict(pairs)
        ranked = []
        for h, score in zip(hits, scores):
            h = dict(h)
            h["rerank_score"] = float(score)
            ranked.append(h)
        ranked.sort(key=lambda h: h.get("rerank_score", h.get("score", 0.0)), reverse=True)
        return ranked[:top_k]
    except Exception as exc:  # noqa: BLE001 - optional quality layer
        log.warning("Reranker unavailable/skipped (%s): %s", model_name, exc)
        return hits[:top_k]
