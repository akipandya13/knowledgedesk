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


# ── Roles ────────────────────────────────────────────────────────────
# member       — asks questions, sees the document list, gives feedback
# tenant_admin — everything a member can, plus documents, users, settings,
#                connectors and insights for their own tenant
# superadmin   — platform operator: tenants, users, platform stats, audit.
#                Deliberately has NO access to tenant document content.
ROLE_MEMBER = "member"
ROLE_TENANT_ADMIN = "tenant_admin"
ROLE_SUPERADMIN = "superadmin"
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
    _add_column_if_missing("query_log", "filters_json", "filters_json JSON DEFAULT '{}'")
    _add_column_if_missing("query_log", "cost_estimate_usd", "cost_estimate_usd FLOAT DEFAULT 0.0")


def new_api_key() -> str:
    return "kd-" + secrets.token_urlsafe(24)
