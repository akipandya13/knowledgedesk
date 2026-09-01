"""Embeddings with per-tenant model selection and demo-safe guards.

Each tenant can use a different embedding backend:
  * local            — SentenceTransformer, cached by model name (default).
  * openai           — legacy: OPENAI_* env, text-embedding-3-small.
  * openai_compatible — any /v1/embeddings endpoint (from a model connector).
  * azure_foundry    — Azure AI Foundry / Azure OpenAI embeddings deployment.
  * bedrock          — AWS Bedrock (Titan / Cohere embedding models).

Heavy Hugging Face models are not loaded by default because a single query
could otherwise trigger multi-GB downloads on CPU.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, List

import httpx

from .. import observability as obs
from ..config import get_settings
from ..model_catalog import model_warning

_models: dict[str, object] = {}
_lock = threading.Lock()


class ModelLoadBlocked(RuntimeError):
    """Raised when a tenant selected a premium model blocked by safe mode."""


class EmbeddingError(RuntimeError):
    """Raised when a remote embedding backend cannot be used."""


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


def embedding_dim(provider: str | None = None, model_name: str | None = None,
                  runtime: dict[str, Any] | None = None) -> int:
    s = get_settings()
    provider = provider or s.embedding_provider
    model_name = model_name or s.embedding_model
    if provider in ("local", ""):
        return _local_model(model_name).get_sentence_embedding_dimension()
    if provider == "openai":
        return 1536
    # Remote connector: trust the admin-declared dimension, else probe once.
    declared = (runtime or {}).get("embedding_dimensions")
    if declared:
        return int(declared)
    return len(embed_texts(["dimension probe"], provider=provider,
                           model_name=model_name, runtime=runtime)[0])


def embed_texts(texts: List[str], provider: str | None = None,
                model_name: str | None = None, batch_size: int | None = None,
                runtime: dict[str, Any] | None = None) -> List[List[float]]:
    s = get_settings()
    runtime = runtime or {}
    provider = provider or s.embedding_provider
    model_name = model_name or s.embedding_model
    t0 = time.perf_counter()
    try:
        # Retry only the network-backed providers on a transient blip; a local
        # model failure (OOM, bad model) is deterministic and fails fast.
        if provider in ("local", ""):
            vecs = _embed_dispatch(texts, provider, model_name, batch_size, runtime, s)
        else:
            from ..resilience import retry_call
            import httpx as _httpx
            vecs = retry_call(
                lambda: _embed_dispatch(texts, provider, model_name, batch_size, runtime, s),
                op=f"embedding.{provider}",
                retry_on=(_httpx.TransportError, _httpx.HTTPStatusError,
                          ConnectionError, TimeoutError))
        obs.count("embedding.calls", provider=provider, outcome="ok")
        return vecs
    except Exception:
        obs.count("embedding.calls", provider=provider, outcome="error")
        raise
    finally:
        obs.observe("embedding.batch.seconds", time.perf_counter() - t0, provider=provider,
                    help="Embedding batch latency")
        obs.observe("embedding.batch.texts", len(texts), provider=provider)


def _embed_dispatch(texts, provider, model_name, batch_size, runtime, s):
    if provider in ("local", ""):
        model = _local_model(model_name)
        vectors = model.encode(
            texts,
            batch_size=batch_size or s.embedding_batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.tolist() for v in vectors]
    if provider == "openai":
        return _embed_openai(texts)
    if provider == "openai_compatible":
        return _embed_oai_compatible(
            texts, model_name,
            base_url=runtime.get("embedding_base_url") or s.openai_base_url,
            api_key=runtime.get("embedding_api_key", ""),
        )
    if provider == "ollama":
        return _embed_ollama(texts, model_name,
                             runtime.get("embedding_base_url") or s.ollama_url)
    if provider == "azure_foundry":
        return _embed_azure(texts, runtime)
    if provider == "bedrock":
        return _embed_bedrock(texts, model_name, runtime)
    raise EmbeddingError(f"Unsupported embedding provider: {provider}")


def embed_query(text: str, provider: str | None = None, model_name: str | None = None,
                runtime: dict[str, Any] | None = None) -> List[float]:
    return embed_texts([text], provider=provider, model_name=model_name, runtime=runtime)[0]


# ── Remote backends ────────────────────────────────────────────────

def _embed_openai(texts: List[str]) -> List[List[float]]:
    s = get_settings()
    return _embed_oai_compatible(texts, "text-embedding-3-small",
                                 base_url=s.openai_base_url, api_key=s.openai_api_key)


def _embed_oai_compatible(texts: List[str], model: str, base_url: str,
                          api_key: str) -> List[List[float]]:
    out: List[List[float]] = []
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=60) as client:
        for i in range(0, len(texts), 100):
            batch = texts[i:i + 100]
            r = client.post(f"{base_url.rstrip('/')}/embeddings", headers=headers,
                            json={"model": model, "input": batch})
            r.raise_for_status()
            out.extend(item["embedding"] for item in r.json()["data"])
    return out


def _embed_ollama(texts: List[str], model: str, base_url: str) -> List[List[float]]:
    url = f"{base_url.rstrip('/')}/api/embed"
    with httpx.Client(timeout=120) as client:
        r = client.post(url, json={"model": model, "input": texts})
        r.raise_for_status()
        data = r.json()
    embs = data.get("embeddings")
    if not embs:
        raise EmbeddingError(f"Ollama returned no embeddings for model '{model}'.")
    return embs


def _embed_azure(texts: List[str], runtime: dict[str, Any]) -> List[List[float]]:
    endpoint = str(runtime.get("embedding_endpoint", "")).rstrip("/")
    deployment = runtime.get("embedding_deployment", "")
    version = runtime.get("embedding_api_version", "")
    key = runtime.get("embedding_api_key", "")
    if not (endpoint and deployment and version and key):
        raise EmbeddingError("Azure embedding connector is missing endpoint, deployment, api_version, or api_key.")
    url = f"{endpoint}/openai/deployments/{deployment}/embeddings?api-version={version}"
    out: List[List[float]] = []
    with httpx.Client(timeout=60) as client:
        for i in range(0, len(texts), 100):
            batch = texts[i:i + 100]
            r = client.post(url, headers={"api-key": key}, json={"input": batch})
            r.raise_for_status()
            out.extend(item["embedding"] for item in r.json()["data"])
    return out


def _embed_bedrock(texts: List[str], model: str, runtime: dict[str, Any]) -> List[List[float]]:
    try:
        import boto3  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise EmbeddingError("boto3 is not installed; cannot use an AWS Bedrock embedding connector.") from e
    region = runtime.get("embedding_region") or "us-east-1"
    kwargs: dict[str, Any] = {"region_name": region}
    if runtime.get("embedding_aws_access_key_id") and runtime.get("embedding_aws_secret_access_key"):
        kwargs["aws_access_key_id"] = runtime["embedding_aws_access_key_id"]
        kwargs["aws_secret_access_key"] = runtime["embedding_aws_secret_access_key"]
        if runtime.get("embedding_aws_session_token"):
            kwargs["aws_session_token"] = runtime["embedding_aws_session_token"]
    client = boto3.client("bedrock-runtime", **kwargs)
    is_cohere = "cohere" in (model or "").lower()
    out: List[List[float]] = []
    try:
        if is_cohere:
            for i in range(0, len(texts), 96):
                batch = texts[i:i + 96]
                resp = client.invoke_model(modelId=model, body=json.dumps(
                    {"texts": batch, "input_type": "search_document"}))
                out.extend(json.loads(resp["body"].read())["embeddings"])
        else:  # Amazon Titan — one text per call
            for text in texts:
                resp = client.invoke_model(modelId=model, body=json.dumps({"inputText": text}))
                out.append(json.loads(resp["body"].read())["embedding"])
    except Exception as e:  # noqa: BLE001 — boto3 client errors
        raise EmbeddingError(f"AWS Bedrock embedding failed for '{model}': {e}") from e
    return out
