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
    refresh_token_days: int = 14                 # per-rotation rolling expiry
    # Session lifetime, enforced across refresh-token rotations:
    auth_session_idle_hours: int = 72            # no refresh within this window → re-login
    auth_session_max_days: int = 30              # absolute cap; a session cannot outlive this
    auth_max_sessions_per_user: int = 10         # oldest evicted past this
    password_min_length: int = 10
    login_max_failures: int = 5
    login_lockout_minutes: int = 15

    # ── Authentication hardening ────────────────────────────────────
    # Login throttling (sliding window, in-process). Complements per-account lockout.
    auth_login_rate_per_min: int = 12           # per (ip + email)
    auth_login_rate_ip_per_min: int = 60        # per ip across all accounts
    # Password policy (min_length above still applies)
    auth_pw_require_upper: bool = False
    auth_pw_require_lower: bool = False
    auth_pw_require_digit: bool = False
    auth_pw_require_symbol: bool = False
    auth_pw_history: int = 5                     # reject reuse of the last N hashes
    auth_pw_breach_check: bool = False           # HIBP k-anonymity range API (keyless)
    auth_pw_max_age_days: int = 0                # 0 = no expiry; >0 forces a change past this age
    # MFA (TOTP). Per-user opt-in; tenants may require it (settings_json.mfa_required).
    auth_totp_issuer: str = "KnowledgeDesk"
    auth_mfa_token_minutes: int = 5              # lifetime of the interim MFA challenge token
    # Legacy X-Admin-Key bypass — off by default now.
    auth_legacy_admin_key_enabled: bool = False
    # Optional: also set the refresh token as an httpOnly cookie on login/refresh.
    auth_refresh_cookie: bool = False
    auth_cookie_secure: bool = True
    # CORS
    cors_allow_origins: str = "*"                # comma list; "*" = any

    # ── TLS / reverse proxy ────────────────────────────────────────
    # The app's public origin (scheme+host). Used for SSO redirect URIs and
    # email links so they are correct behind the TLS proxy. Set to
    # https://<KD_DOMAIN> in production.
    public_base_url: str = ""
    # Host allow-list (Host header). "*" disables the check.
    trusted_hosts: str = "*"
    # In-app HTTP→HTTPS redirect. Usually the proxy (Caddy) does this; enable
    # only if the app is directly internet-facing.
    force_https_redirect: bool = False
    # Trust X-Forwarded-For / X-Real-IP for the client IP recorded in the audit
    # and activity logs. Safe when the app only ever receives traffic through the
    # reverse proxy; set false if the app is directly internet-facing.
    trust_forwarded_for: bool = True

    # ── Governance: audit trail & user activity tracking ───────────
    # Audit log = the tamper-evident compliance record (hash-chained per
    # workspace). Activity log = the higher-volume behavioural stream (who
    # viewed / ran / exported what). See docs/GOVERNANCE.md.
    audit_retention_days: int = 0        # 0 = keep forever (compliance default)
    activity_log_enabled: bool = True
    activity_log_requests: bool = True   # capture every authenticated API call
    activity_retention_days: int = 90    # trimmed by scripts/purge_logs.py

    # ── Transactional email (verification / password reset) ─────────
    email_sender: str = "console"               # console | smtp | noop
    email_from: str = "no-reply@knowledgedesk.local"
    email_public_base_url: str = "http://localhost:3000"   # base for links in emails
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True

    # ── Subscription entitlements (feature gates) ───────────────────
    # Comma list, "*" = everything. Per-tenant overrides live in
    # tenant.settings_json["entitlements"]. Known: sso
    entitlements: str = ""

    # Bootstrap accounts (created at first startup if missing).
    # See DEFAULT_USERS_AND_PASSWORDS.md. Override in .env for anything real.
    superadmin_email: str = "superadmin@knowledgedesk.local"
    superadmin_password: str = "Superadmin!Kd1"
    superadmin_force_password_change: bool = False      # True → prompt on first login
    demo_users_enabled: bool = True                     # demo tenant_admin + member
    demo_admin_email: str = "admin@demo.knowledgedesk.local"
    demo_admin_password: str = "TenantAdmin!Kd1"
    demo_member_email: str = "member@demo.knowledgedesk.local"
    demo_member_password: str = "Member!Kd1234"

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

    # ── Observability ────────────────────────────────────────────────
    # Open, pluggable monitoring. The metric registry is always on; where signals
    # are also *sent* is chosen here. See docs/OBSERVABILITY.md.
    observability_enabled: bool = True
    # Comma list of sink names: noop | stdout | sqlite | prometheus | webhook | otlp | postgres | mongodb
    observability_sinks: str = "stdout,sqlite,prometheus"
    observability_service_name: str = "knowledgedesk"
    observability_sample_traces: float = 1.0          # 0..1 span sampling
    observability_max_series: int = 2000              # per-metric cardinality cap
    observability_health_probe_seconds: int = 30      # 0 disables the background dependency probe
    obs_resource_metrics_seconds: int = 15            # host/process resource-utilization collector; 0 disables

    obs_stdout_pretty: bool = False
    obs_stdout_metrics: bool = False                  # metrics are noisy on stdout
    obs_sqlite_path: str = ""                         # default {DATA_DIR}/observability.db
    obs_sqlite_retention_hours: int = 168
    obs_prometheus_path: str = "/metrics"
    obs_prometheus_token: str = ""                    # optional bearer for /metrics
    obs_webhook_url: str = ""
    obs_webhook_token: str = ""
    obs_webhook_batch: int = 100
    obs_otlp_endpoint: str = ""                       # e.g. http://otel-collector:4318
    obs_otlp_headers: str = ""                        # "k=v,k2=v2"

    # ── Centralized log collection: SQL (Postgres) / NoSQL (Mongo) ───
    # Config-selected, not hardcoded: pick whichever a deployment/customer
    # already runs by adding the name to OBSERVABILITY_SINKS. Neither driver is
    # imported unless its sink is actually selected. See docs/LOGGING.md.
    obs_postgres_dsn: str = ""       # postgresql://user:pass@host:5432/dbname
    obs_postgres_table: str = "kd_logs"
    obs_postgres_batch: int = 50
    obs_mongo_uri: str = ""          # mongodb://user:pass@host:27017
    obs_mongo_db: str = "knowledgedesk"
    obs_mongo_collection: str = "logs"
    obs_mongo_batch: int = 50

    # ── Application logging ──────────────────────────────────────────
    # Every stdlib `logging` call (this app's modules, dependencies, uvicorn's
    # own access/error logs) is emitted as one JSON line carrying the same
    # request_id/tenant/actor as observability events — see app/logging_setup.py.
    log_level: str = "INFO"
    log_format: str = "json"          # json | text (text is easier to read locally)
    # WARNING+ log records are also mirrored into the observability event
    # stream (kind="app.log") so they reach whatever sinks are configured —
    # including postgres/mongodb above — without duplicating the concern.
    log_bridge_level: str = "WARNING"

    # ── Secret resolution ─────────────────────────────────────────
    # Any secret value (config or a stored connector field) may be a reference
    # ${provider:locator}. See docs/SECRETS_MANAGEMENT.md.
    secrets_cache_ttl: int = 300

    @property
    def app_base_url(self) -> str:
        """The app's public origin for building outward-facing links."""
        return (self.public_base_url or self.email_public_base_url or
                "http://localhost:3000").rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
