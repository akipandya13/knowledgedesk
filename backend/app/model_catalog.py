"""Curated local/open-weight model profiles for tenant-admin selection.

The catalog exposes premium models for enterprise deployments, but the Docker
POC defaults to a fast laptop-safe profile. Heavy Hugging Face models are
blocked by default at runtime unless ALLOW_HEAVY_LOCAL_MODELS=true is set.
"""
from __future__ import annotations

import re
from typing import Any

# Profiles are ordered with the safest demo default first. Premium choices remain
# available from the admin dropdown, but require GPU/storage planning.
MODEL_PROFILES: dict[str, dict[str, Any]] = {
    "demo_fast": {
        "label": "Demo Fast / Laptop Safe",
        "description": "Default: fast CPU/laptop demo profile. No huge model download during first Q&A.",
        "embedding_provider": "local",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "reranker_enabled": False,
        "reranker_model": "",
        "rerank_top_k": 0,
        "llm_provider": "ollama",
        "llm_model": "gemma3:4b",
        "retrieval_top_k": 12,
        "retrieval_score_threshold": 0.28,
        "retrieval_max_context_chars": 9000,
        "llm_temperature": 0.1,
        "llm_max_tokens": 700,
        "requires_gpu": False,
        "demo_safe": True,
    },
    "enterprise_balanced": {
        "label": "Enterprise Balanced",
        "description": "Recommended production baseline: strong BGE retrieval + reranking + Gemma 12B. Better quality, slower on CPU.",
        "embedding_provider": "local",
        "embedding_model": "BAAI/bge-m3",
        "reranker_enabled": True,
        "reranker_model": "BAAI/bge-reranker-large",
        "rerank_top_k": 8,
        "llm_provider": "ollama",
        "llm_model": "gemma3:12b",
        "retrieval_top_k": 32,
        "retrieval_score_threshold": 0.25,
        "retrieval_max_context_chars": 12000,
        "llm_temperature": 0.1,
        "llm_max_tokens": 900,
        "requires_gpu": False,
        "demo_safe": False,
    },
    "premium_best": {
        "label": "Premium Best Quality / GPU",
        "description": "Highest-quality local/open-weight profile. Requires heavy Hugging Face downloads, HF_TOKEN recommended, and a strong GPU server.",
        "embedding_provider": "local",
        "embedding_model": "Qwen/Qwen3-Embedding-4B",
        "reranker_enabled": True,
        "reranker_model": "Qwen/Qwen3-Reranker-4B",
        "rerank_top_k": 8,
        "llm_provider": "ollama",
        "llm_model": "gemma3:27b",
        "retrieval_top_k": 40,
        "retrieval_score_threshold": 0.22,
        "retrieval_max_context_chars": 16000,
        "llm_temperature": 0.1,
        "llm_max_tokens": 1200,
        "requires_gpu": True,
        "demo_safe": False,
    },
    "multilingual_efficient": {
        "label": "Multilingual Efficient",
        "description": "Good multilingual quality. Jina v3 may require trust_remote_code and initial model download.",
        "embedding_provider": "local",
        "embedding_model": "jinaai/jina-embeddings-v3",
        "reranker_enabled": True,
        "reranker_model": "BAAI/bge-reranker-v2-m3",
        "rerank_top_k": 6,
        "llm_provider": "ollama",
        "llm_model": "gemma3:12b",
        "retrieval_top_k": 30,
        "retrieval_score_threshold": 0.24,
        "retrieval_max_context_chars": 11000,
        "llm_temperature": 0.1,
        "llm_max_tokens": 900,
        "requires_gpu": False,
        "demo_safe": False,
    },
    "extractive_zero_llm": {
        "label": "Zero LLM Cost / Extractive",
        "description": "No generation model; returns cited excerpts only. Useful for locked-down tenants.",
        "embedding_provider": "local",
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "reranker_enabled": False,
        "reranker_model": "",
        "rerank_top_k": 0,
        "llm_provider": "none",
        "llm_model": "none",
        "retrieval_top_k": 12,
        "retrieval_score_threshold": 0.28,
        "retrieval_max_context_chars": 9000,
        "llm_temperature": 0.0,
        "llm_max_tokens": 0,
        "requires_gpu": False,
        "demo_safe": True,
    },
}

EMBEDDING_MODELS = [
    {"value": "sentence-transformers/all-MiniLM-L6-v2", "label": "MiniLM — laptop/demo fast", "provider": "local", "demo_safe": True, "requires_gpu": False, "notes": "Small, fast, good enough for demo."},
    {"value": "BAAI/bge-m3", "label": "BGE-M3 — enterprise default", "provider": "local", "demo_safe": False, "requires_gpu": False, "notes": "Stronger retrieval; larger download and slower on CPU."},
    {"value": "jinaai/jina-embeddings-v3", "label": "Jina Embeddings v3 — multilingual efficient", "provider": "local", "demo_safe": False, "requires_gpu": False, "notes": "Good multilingual option; larger than MiniLM."},
    {"value": "mixedbread-ai/mxbai-embed-large-v1", "label": "MxBai Embed Large — strong English", "provider": "local", "demo_safe": False, "requires_gpu": False, "notes": "Strong English retrieval."},
    {"value": "nomic-ai/nomic-embed-text-v1.5", "label": "Nomic Embed v1.5 — efficient local", "provider": "local", "demo_safe": False, "requires_gpu": False, "notes": "Efficient local retrieval model."},
    {"value": "Qwen/Qwen3-Embedding-4B", "label": "Qwen3 Embedding 4B — best quality / GPU", "provider": "local", "demo_safe": False, "requires_gpu": True, "heavy": True, "notes": "Very large. Blocked unless ALLOW_HEAVY_LOCAL_MODELS=true."},
]

RERANKER_MODELS = [
    {"value": "", "label": "Disabled — recommended for MacBook/demo", "demo_safe": True, "requires_gpu": False},
    {"value": "BAAI/bge-reranker-base", "label": "BGE Reranker Base — quality boost, downloads on first use", "demo_safe": False, "requires_gpu": False},
    {"value": "BAAI/bge-reranker-large", "label": "BGE Reranker Large — recommended default", "demo_safe": False, "requires_gpu": False},
    {"value": "BAAI/bge-reranker-v2-m3", "label": "BGE Reranker v2 M3 — multilingual", "demo_safe": False, "requires_gpu": False},
    {"value": "Qwen/Qwen3-Reranker-4B", "label": "Qwen3 Reranker 4B — best quality / GPU", "demo_safe": False, "requires_gpu": True, "heavy": True},
]

LLM_MODELS = [
    {"value": "none", "label": "No LLM — extractive cited excerpts", "provider": "none", "demo_safe": True, "requires_gpu": False},
    {"value": "gemma3:4b", "label": "Gemma 3 4B — fast demo", "provider": "ollama", "demo_safe": True, "requires_gpu": False},
    {"value": "gemma3:12b", "label": "Gemma 3 12B — enterprise balanced", "provider": "ollama", "demo_safe": False, "requires_gpu": False},
    {"value": "gemma3:27b", "label": "Gemma 3 27B — best Gemma quality / GPU recommended", "provider": "ollama", "demo_safe": False, "requires_gpu": True},
    {"value": "qwen3:14b", "label": "Qwen3 14B — balanced reasoning", "provider": "ollama", "demo_safe": False, "requires_gpu": False},
    {"value": "qwen3:32b", "label": "Qwen3 32B — strong reasoning / GPU recommended", "provider": "ollama", "demo_safe": False, "requires_gpu": True},
    {"value": "mistral-small:24b", "label": "Mistral Small 24B — enterprise quality", "provider": "ollama", "demo_safe": False, "requires_gpu": True},
    {"value": "llama3.3:70b", "label": "Llama 3.3 70B — premium GPU", "provider": "ollama", "demo_safe": False, "requires_gpu": True},
]

MODEL_SETTING_KEYS = {
    "model_profile",
    "embedding_provider", "embedding_model",
    "reranker_enabled", "reranker_model", "rerank_top_k",
    "llm_provider", "llm_model", "openai_model",
    "llm_connector_id", "embedding_connector_id",
    "retrieval_top_k", "retrieval_score_threshold", "retrieval_max_context_chars",
    "llm_temperature", "llm_max_tokens", "answer_language",
}

# ── Model connectors ────────────────────────────────────────────────
# Describes the fields each connector provider needs. `config` fields are
# stored in ModelConnector.config_json; `secret` fields are Fernet-encrypted
# into ModelConnector.secret_encrypted and never returned by the API.
CONNECTOR_PROVIDERS = {
    "bedrock": {
        "label": "AWS Bedrock",
        "kinds": ["llm", "embedding"],
        "model_id_hint": "llm: anthropic.claude-3-5-sonnet-20240620-v1:0 · embedding: amazon.titan-embed-text-v2:0",
        "config_fields": [
            {"key": "region", "label": "AWS region", "required": True, "placeholder": "us-east-1"},
            {"key": "dimensions", "label": "Embedding dimensions (embedding only)", "required": False, "placeholder": "1024"},
        ],
        "secret_fields": [
            {"key": "aws_access_key_id", "label": "AWS access key ID", "required": False},
            {"key": "aws_secret_access_key", "label": "AWS secret access key", "required": False},
            {"key": "aws_session_token", "label": "AWS session token (optional)", "required": False},
        ],
        "secret_note": "Leave AWS keys blank to use the host's default credential chain (IAM role, ~/.aws).",
    },
    "azure_foundry": {
        "label": "Azure AI Foundry",
        "kinds": ["llm", "embedding"],
        "model_id_hint": "the underlying model name, e.g. gpt-4o or text-embedding-3-large",
        "config_fields": [
            {"key": "endpoint", "label": "Resource endpoint", "required": True, "placeholder": "https://my-resource.openai.azure.com"},
            {"key": "deployment", "label": "Deployment name", "required": True, "placeholder": "gpt-4o"},
            {"key": "api_version", "label": "API version", "required": True, "placeholder": "2024-06-01"},
            {"key": "dimensions", "label": "Embedding dimensions (embedding only)", "required": False, "placeholder": "3072"},
        ],
        "secret_fields": [
            {"key": "api_key", "label": "API key", "required": True},
        ],
    },
    "ollama": {
        "label": "Local — Ollama (SLM / MLM)",
        "kinds": ["llm", "embedding"],
        "model_id_hint": "gemma3:4b (SLM) · gemma3:12b (MLM) · nomic-embed-text (embedding)",
        "config_fields": [
            {"key": "base_url", "label": "Ollama URL", "required": False, "placeholder": "http://ollama:11434"},
            {"key": "size_class", "label": "Size class", "required": False, "placeholder": "slm | mlm"},
        ],
        "secret_fields": [],
    },
    "openai_compatible": {
        "label": "Local / hosted — OpenAI-compatible endpoint",
        "kinds": ["llm", "embedding"],
        "model_id_hint": "model name the endpoint expects, e.g. gpt-4o-mini",
        "config_fields": [
            {"key": "base_url", "label": "Base URL (/v1)", "required": True, "placeholder": "http://vllm:8000/v1"},
            {"key": "dimensions", "label": "Embedding dimensions (embedding only)", "required": False},
        ],
        "secret_fields": [
            {"key": "api_key", "label": "API key (optional for local)", "required": False},
        ],
    },
    "none": {
        "label": "None — extractive answers, no LLM",
        "kinds": ["llm"],
        "model_id_hint": "",
        "config_fields": [],
        "secret_fields": [],
    },
}

REMOTE_CONNECTOR_PROVIDERS = {"bedrock", "azure_foundry", "openai_compatible"}


# ── Data connectors (per-workspace external document sources) ───────
# Same field-spec shape as CONNECTOR_PROVIDERS. `multiline` renders a textarea.
DATA_CONNECTOR_PROVIDERS = {
    "gdrive": {
        "label": "Google Drive",
        "config_fields": [
            {"key": "folder_id", "label": "Folder ID", "required": True,
             "placeholder": "the long id from the folder URL"},
            {"key": "impersonate_email", "label": "Impersonate user (domain-wide delegation)",
             "required": False, "placeholder": "optional — user@company.com"},
        ],
        "secret_fields": [
            {"key": "service_account_json", "label": "Service account key (JSON)",
             "required": True, "multiline": True},
        ],
        "secret_note": "Create a service account in Google Cloud, enable the Drive API, then either "
                       "share the target folder with the service-account email or configure "
                       "domain-wide delegation and set an impersonation user above.",
    },
    "sharepoint": {
        "label": "SharePoint / OneDrive (Microsoft Graph)",
        "config_fields": [
            {"key": "tenant_id", "label": "Directory (tenant) ID", "required": True},
            {"key": "client_id", "label": "Application (client) ID", "required": True},
            {"key": "site_id", "label": "SharePoint site ID", "required": True,
             "placeholder": "contoso.sharepoint.com,<guid>,<guid>"},
            {"key": "drive_id", "label": "Drive ID (optional)", "required": False,
             "placeholder": "defaults to the site's document library"},
        ],
        "secret_fields": [
            {"key": "client_secret", "label": "Client secret", "required": True},
        ],
        "secret_note": "Azure AD app registration with the Sites.Read.All application permission "
                       "(admin-consented).",
    },
}

HEAVY_LOCAL_MODELS = {
    "Qwen/Qwen3-Embedding-4B": "Qwen3 Embedding 4B is a premium GPU-size embedding model and will download multiple large safetensor shards.",
    "Qwen/Qwen3-Reranker-4B": "Qwen3 Reranker 4B is a premium GPU-size reranker model and will download multiple large safetensor shards.",
}


SAFE_DEMO_OLLAMA_MODELS = {"gemma3:4b"}
LARGE_OLLAMA_MODELS = {
    "gemma3:12b": "Gemma 3 12B is not MacBook-demo safe unless pre-pulled and you allow large Ollama models.",
    "gemma3:27b": "Gemma 3 27B is a premium/GPU-size model.",
    "qwen3:14b": "Qwen3 14B is large for a 16 GB MacBook Docker demo.",
    "qwen3:32b": "Qwen3 32B is a premium/GPU-size model.",
    "mistral-small:24b": "Mistral Small 24B is a premium/GPU-size model.",
    "llama3.3:70b": "Llama 3.3 70B is a premium/GPU-size model.",
}

OPTIONAL_RERANKER_MODELS = {
    "BAAI/bge-reranker-base": "BGE Reranker Base is optional and still downloads/loads a CrossEncoder model on first query.",
    "BAAI/bge-reranker-large": "BGE Reranker Large is optional and can be slow on CPU/MacBook demos.",
    "BAAI/bge-reranker-v2-m3": "BGE Reranker v2 M3 is optional and can be slow on CPU/MacBook demos.",
    "Qwen/Qwen3-Reranker-4B": "Qwen3 Reranker 4B is a premium GPU-size reranker model and will download multiple large safetensor shards.",
}


def safe_slug(value: str) -> str:
    """Stable slug for Qdrant collection names."""
    value = (value or "default").lower()
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")[:64] or "default"


def catalog_payload() -> dict[str, Any]:
    return {
        "profiles": [dict(key=k, **v) for k, v in MODEL_PROFILES.items()],
        "embedding_models": EMBEDDING_MODELS,
        "reranker_models": RERANKER_MODELS,
        "llm_models": LLM_MODELS,
        "heavy_local_models": HEAVY_LOCAL_MODELS,
        "large_ollama_models": LARGE_OLLAMA_MODELS,
        "safe_demo_ollama_models": sorted(SAFE_DEMO_OLLAMA_MODELS),
        "optional_reranker_models": OPTIONAL_RERANKER_MODELS,
        "connector_providers": CONNECTOR_PROVIDERS,
    }


def profile_defaults(profile_key: str | None) -> dict[str, Any]:
    if not profile_key:
        return {}
    return dict(MODEL_PROFILES.get(profile_key, {}))


def model_warning(model_name: str | None) -> str | None:
    if not model_name:
        return None
    return HEAVY_LOCAL_MODELS.get(model_name) or LARGE_OLLAMA_MODELS.get(model_name)
