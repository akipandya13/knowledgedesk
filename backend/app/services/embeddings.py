"""Embeddings with per-tenant model selection and demo-safe guards.

Each tenant can use a different embedding model. Local SentenceTransformer
instances are cached by model name. Heavy Hugging Face models are not loaded by
default because a single query could otherwise trigger multi-GB downloads on CPU.
"""
from __future__ import annotations

import os
import threading
from typing import List

import httpx

from ..config import get_settings
from ..model_catalog import model_warning

_models: dict[str, object] = {}
_lock = threading.Lock()


class ModelLoadBlocked(RuntimeError):
    """Raised when a tenant selected a premium model blocked by safe mode."""


def _guard_model(model_name: str) -> None:
    s = get_settings()
    warning = model_warning(model_name)
    if warning and not s.allow_heavy_local_models:
        raise ModelLoadBlocked(
            f"{warning} The Docker demo blocks this by default to avoid slow multi-GB downloads on CPU. "
            "In Settings choose 'Demo Fast / Laptop Safe' or 'Enterprise Balanced', or set "
            "ALLOW_HEAVY_LOCAL_MODELS=true and HF_TOKEN=<token> for a GPU/premium deployment."
        )


def _local_model(model_name: str):
    _guard_model(model_name)
    s = get_settings()
    if s.hf_token and not os.environ.get("HF_TOKEN"):
        os.environ["HF_TOKEN"] = s.hf_token
    if model_name not in _models:
        with _lock:
            if model_name not in _models:
                from sentence_transformers import SentenceTransformer
                try:
                    _models[model_name] = SentenceTransformer(model_name, trust_remote_code=True)
                except TypeError:
                    _models[model_name] = SentenceTransformer(model_name)
    return _models[model_name]


def embedding_dim(provider: str | None = None, model_name: str | None = None) -> int:
    s = get_settings()
    provider = provider or s.embedding_provider
    model_name = model_name or s.embedding_model
    if provider == "openai":
        return 1536
    return _local_model(model_name).get_sentence_embedding_dimension()


def embed_texts(texts: List[str], provider: str | None = None,
                model_name: str | None = None, batch_size: int | None = None) -> List[List[float]]:
    s = get_settings()
    provider = provider or s.embedding_provider
    model_name = model_name or s.embedding_model
    if provider == "openai":
        return _embed_openai(texts)
    model = _local_model(model_name)
    vectors = model.encode(
        texts,
        batch_size=batch_size or s.embedding_batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str, provider: str | None = None, model_name: str | None = None) -> List[float]:
    return embed_texts([text], provider=provider, model_name=model_name)[0]


def _embed_openai(texts: List[str]) -> List[List[float]]:
    s = get_settings()
    out: List[List[float]] = []
    with httpx.Client(timeout=60) as client:
        for i in range(0, len(texts), 100):
            batch = texts[i:i + 100]
            r = client.post(
                f"{s.openai_base_url}/embeddings",
                headers={"Authorization": f"Bearer {s.openai_api_key}"},
                json={"model": "text-embedding-3-small", "input": batch},
            )
            r.raise_for_status()
            out.extend(item["embedding"] for item in r.json()["data"])
    return out
