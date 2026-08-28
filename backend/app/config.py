"""Central configuration. Every value can be overridden from .env / environment.

Defaults are chosen so the system runs with zero changes:
local embeddings, local Gemma via Ollama, Qdrant from docker-compose.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Identity
    app_name: str = "KnowledgeDesk"
    environment: str = "demo"

    # Security — API keys (tenant-scoped service accounts for integrations)
    admin_api_key: str = "kd-admin-key"                 # legacy; superseded by superadmin login
    demo_tenant_enabled: bool = True
    demo_tenant_api_key: str = "kd-demo-key"

    # Security — JWT user authentication
    jwt_secret: str = ""                  # empty → auto-generated & persisted in DATA_DIR

    # Security — model connector credential encryption (Fernet master key).
    # Empty → auto-generated & persisted to {data_dir}/secret.key. In production
    # this should be supplied from a KMS / secrets manager, not a file.
    kd_secret_key: str = ""
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    password_min_length: int = 10
    login_max_failures: int = 5
    login_lockout_minutes: int = 15

    # Bootstrap accounts (created at first startup if missing)
    superadmin_email: str = "superadmin@knowledgedesk.local"
    superadmin_password: str = "ChangeMe!Now1"          # forced change on first login
    demo_users_enabled: bool = True                     # demo tenant admin + member

    # Model profile defaults. Tenant admins can override these per workspace.
    model_profile: str = "demo_fast"

    # LLM
    llm_provider: str = "ollama"            # ollama | openai_compatible | none
    llm_model: str = "gemma3:4b"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 900
    llm_timeout_seconds: int = 300
    llm_fallback_to_extractive: bool = True
    ollama_auto_pull_safe_models: bool = True
    allow_large_ollama_models: bool = False

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Embeddings
    embedding_provider: str = "local"       # local | openai
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_batch_size: int = 64
    allow_heavy_local_models: bool = False
    auto_downgrade_blocked_models: bool = True
    laptop_safe_mode: bool = True       # MacBook/16GB demo mode: blocks optional HF reranker downloads unless explicitly allowed
    allow_reranker_models: bool = False # true only when you accept local CrossEncoder download/load latency
    hf_token: str = ""       # optional; raises Hugging Face rate limits for premium local models

    # Optional reranker. This is usually the biggest quality upgrade after
    # moving from a small embedding model to an enterprise embedding model.
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-base"
    rerank_top_k: int = 8

    # Retrieval
    retrieval_top_k: int = 12
    retrieval_score_threshold: float = 0.28
    retrieval_max_context_chars: int = 9000

    # Chunking
    chunk_size: int = 1100
    chunk_overlap: int = 180
    max_upload_mb: int = 50

    # Answer behaviour
    answer_language: str = "auto"
    answer_refuse_outside_knowledge: bool = True
    answer_include_citations: bool = True

    # Connectors
    gdrive_access_token: str = ""
    gdrive_folder_id: str = ""
    msgraph_tenant_id: str = ""
    msgraph_client_id: str = ""
    msgraph_client_secret: str = ""
    msgraph_site_id: str = ""
    msgraph_drive_id: str = ""

    # Infrastructure
    qdrant_url: str = "http://localhost:6333"
    ollama_url: str = "http://localhost:11434"
    data_dir: str = "/data"


@lru_cache
def get_settings() -> Settings:
    return Settings()
