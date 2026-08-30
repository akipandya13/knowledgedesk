"""SQLite metadata store: tenants, documents, query log.

Vector data lives in Qdrant; this DB only tracks "what exists and what happened",
so it stays tiny and needs no external service.
"""
import os
import secrets
import datetime as dt

from sqlalchemy import (create_engine, Column, Integer, String, Float, Text,
                        DateTime, ForeignKey, JSON, Boolean)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from .config import get_settings

settings = get_settings()
os.makedirs(settings.data_dir, exist_ok=True)

engine = create_engine(
    f"sqlite:///{settings.data_dir}/knowledgedesk.db",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ── Document scope ───────────────────────────────────────────────────
# tenant    — company-wide: published by a tenant_admin, visible to everyone
#             in the workspace.
# workspace — private: owned by one user (owner_user_id), visible only to that
#             user and to tenant_admins.
DOC_SCOPE_TENANT = "tenant"
DOC_SCOPE_WORKSPACE = "workspace"
DOC_SCOPES = {DOC_SCOPE_TENANT, DOC_SCOPE_WORKSPACE}


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, index=True)          # used in Qdrant collection name
    name = Column(String)
    api_key = Column(String, unique=True, index=True)
    settings_json = Column(JSON, default=dict)              # per-tenant overrides (top_k, model, ...)
    created_at = Column(DateTime, default=utcnow)

    documents = relationship("Document", back_populates="tenant", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True)
    filename = Column(String)
    source = Column(String, default="upload")               # upload | gdrive | sharepoint | seed
    status = Column(String, default="queued")               # queued | processing | ready | failed
    error = Column(Text, nullable=True)
    pages = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    size_bytes = Column(Integer, default=0)
    content_hash = Column(String, index=True, default="")
    department = Column(String, default="")
    confidentiality = Column(String, default="internal")
    tags_json = Column(JSON, default=list)
    model_profile = Column(String, default="")
    embedding_provider = Column(String, default="")
    embedding_model = Column(String, default="")
    version = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    # Ownership / visibility. owner_user_id is NULL for company-wide documents.
    scope = Column(String, default=DOC_SCOPE_TENANT, index=True)   # tenant | workspace
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=utcnow)

    tenant = relationship("Tenant", back_populates="documents")


class ModelConnector(Base):
    """A tenant-defined backend for LLM generation or embeddings.

    provider ∈ {bedrock, azure_foundry, ollama, openai_compatible, none}
    secret_encrypted is a Fernet token (see app.crypto); never stored plaintext.
    """
    __tablename__ = "model_connectors"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    kind = Column(String, nullable=False)                   # llm | embedding
    name = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    model_id = Column(String, default="")                   # provider-native model identifier
    config_json = Column(JSON, default=dict)                # non-secret params (region, endpoint, dimensions, ...)
    secret_encrypted = Column(Text, default="")             # Fernet token → {api_key?, aws_*?}
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class DataConnector(Base):
    """A tenant-defined external document source (Google Drive, SharePoint).

    provider ∈ {gdrive, sharepoint}
    secret_encrypted is a Fernet token (see app.crypto); never stored plaintext.
    """
    __tablename__ = "data_connectors"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    config_json = Column(JSON, default=dict)                # non-secret params (folder_id, site_id, ...)
    secret_encrypted = Column(Text, default="")             # Fernet token → {service_account_json? / client_secret?}
    is_active = Column(Boolean, default=True)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String, default="")           # running | success | partial | failed
    last_sync_detail = Column(String, default="")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ConnectorSyncRun(Base):
    """One execution of a DataConnector sync — kept for history in the UI."""
    __tablename__ = "connector_sync_runs"
    id = Column(Integer, primary_key=True)
    connector_id = Column(Integer, ForeignKey("data_connectors.id"), index=True)
    tenant_id = Column(Integer, index=True)
    status = Column(String, default="running")              # running | success | partial | failed
    queued = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    detail = Column(Text, default="")
    started_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime, nullable=True)


# ── Roles ────────────────────────────────────────────────────────────
# member       — asks questions, sees the document list, gives feedback,
#                manages documents in their own workspace
# tenant_admin — everything a member can, plus company-wide documents, users,
#                settings, connectors and insights for their own tenant
# superadmin   — platform operator: tenants, users, platform stats, audit.
#                Deliberately has NO access to tenant document content.
# service      — X-API-Key principal (machine integration); tenant_admin-level
#                content access but cannot manage users. Not a human account.
#
# The authoritative capability model lives in app.rbac (ROLE_PERMISSIONS).
ROLE_MEMBER = "member"
ROLE_TENANT_ADMIN = "tenant_admin"
ROLE_SUPERADMIN = "superadmin"
ROLE_SERVICE = "service"
TENANT_ROLES = {ROLE_MEMBER, ROLE_TENANT_ADMIN}
ROLE_RANK = {ROLE_MEMBER: 1, ROLE_TENANT_ADMIN: 2, ROLE_SUPERADMIN: 3}


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, default="")
    password_hash = Column(String, nullable=False)
    role = Column(String, default=ROLE_MEMBER, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True,
                       index=True)                       # NULL for superadmin
    is_active = Column(Integer, default=1)               # soft disable
    password_version = Column(Integer, default=1)        # bump → all JWTs invalid
    force_password_change = Column(Integer, default=0)
    failed_logins = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    tenant = relationship("Tenant")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    token_hash = Column(String, unique=True, index=True)  # SHA-256, never raw
    expires_at = Column(DateTime)
    revoked = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=True, index=True)  # NULL = platform-level
    actor_email = Column(String, default="")
    actor_role = Column(String, default="")
    action = Column(String, index=True)                  # e.g. auth.login, doc.delete
    detail = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)


class QueryLog(Base):
    __tablename__ = "query_log"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    question = Column(Text)
    answer = Column(Text)
    mode = Column(String, default="llm")                    # llm | extractive | not_found
    confidence = Column(Float, default=0.0)                 # top retrieval score
    latency_ms = Column(Integer, default=0)
    sources_json = Column(JSON, default=list)
    filters_json = Column(JSON, default=dict)
    cost_estimate_usd = Column(Float, default=0.0)
    feedback = Column(Integer, nullable=True)               # 1 = helpful, -1 = not helpful
    created_at = Column(DateTime, default=utcnow)


def _add_column_if_missing(table: str, column: str, ddl: str) -> None:
    """Tiny SQLite migration helper so demo volumes survive v1 upgrades."""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    Base.metadata.create_all(engine)
    # Backward-compatible columns added after the first POC build.
    _add_column_if_missing("documents", "content_hash", "content_hash VARCHAR DEFAULT ''")
    _add_column_if_missing("documents", "department", "department VARCHAR DEFAULT ''")
    _add_column_if_missing("documents", "confidentiality", "confidentiality VARCHAR DEFAULT 'internal'")
    _add_column_if_missing("documents", "tags_json", "tags_json JSON DEFAULT '[]'")
    _add_column_if_missing("documents", "model_profile", "model_profile VARCHAR DEFAULT ''")
    _add_column_if_missing("documents", "embedding_provider", "embedding_provider VARCHAR DEFAULT ''")
    _add_column_if_missing("documents", "embedding_model", "embedding_model VARCHAR DEFAULT ''")
    _add_column_if_missing("documents", "version", "version INTEGER DEFAULT 1")
    _add_column_if_missing("documents", "is_active", "is_active BOOLEAN DEFAULT 1")
    # Document ownership (added with the RBAC document-scope model). Existing rows
    # default to company-wide (scope='tenant', owner_user_id=NULL) so nothing
    # that was visible before disappears.
    _add_column_if_missing("documents", "scope", "scope VARCHAR DEFAULT 'tenant'")
    _add_column_if_missing("documents", "owner_user_id", "owner_user_id INTEGER")
    _add_column_if_missing("query_log", "filters_json", "filters_json JSON DEFAULT '{}'")
    _add_column_if_missing("query_log", "cost_estimate_usd", "cost_estimate_usd FLOAT DEFAULT 0.0")
    _add_column_if_missing("query_log", "user_id", "user_id INTEGER")


def new_api_key() -> str:
    return "kd-" + secrets.token_urlsafe(24)
