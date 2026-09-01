"""SQLite metadata store: tenants, documents, query log.

Vector data lives in Qdrant; this DB only tracks "what exists and what happened",
so it stays tiny and needs no external service.
"""
import os
import secrets
import datetime as dt

from sqlalchemy import (create_engine, Column, Integer, String, Float, Text,
                        DateTime, ForeignKey, JSON, Boolean, UniqueConstraint)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from .config import get_settings
from .crypto import EncryptedJSON, EncryptedText

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

# ── Fine-grained access primitives (see app.authz) ──────────────────
SUBJECT_USER = "user"
SUBJECT_GROUP = "group"
GRANT_ALLOW = "allow"
GRANT_DENY = "deny"

# Ordered sensitivity of the document `confidentiality` field. A user may see a
# document only if its level <= their clearance, when the tenant opts in to
# enforcement. Unknown values are treated as most sensitive.
CONFIDENTIALITY_LEVELS = {
    "public": 10,
    "internal": 20,
    "confidential": 30,
    "restricted": 40,
}
CONFIDENTIALITY_UNKNOWN_LEVEL = 99
DEFAULT_CLEARANCE = 100          # sees everything; existing users keep this


def confidentiality_level(value: str | None) -> int:
    return CONFIDENTIALITY_LEVELS.get((value or "internal").lower(),
                                      CONFIDENTIALITY_UNKNOWN_LEVEL)


TENANT_STATUS_ACTIVE = "active"
TENANT_STATUS_SUSPENDED = "suspended"
TENANT_STATUSES = {TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED}


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, index=True)          # used in Qdrant collection name
    name = Column(String)
    api_key = Column(String, unique=True, index=True)
    settings_json = Column(JSON, default=dict)              # per-tenant overrides (top_k, model, ...)
    # Lifecycle: 'active' | 'suspended'. A suspended workspace rejects every
    # request from its users and service keys (superadmin is unaffected) without
    # losing any data — see app.auth.get_principal.
    status = Column(String, default=TENANT_STATUS_ACTIVE, index=True)
    suspended_at = Column(DateTime, nullable=True)
    suspended_reason = Column(String, default="")
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
    password_changed_at = Column(DateTime, default=utcnow)  # for AUTH_PW_MAX_AGE_DAYS
    force_password_change = Column(Integer, default=0)
    failed_logins = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    clearance = Column(Integer, default=DEFAULT_CLEARANCE)  # ABAC: max confidentiality level
    email_verified = Column(Integer, default=1)          # existing/admin-made accounts trusted
    mfa_enabled = Column(Integer, default=0)
    mfa_secret_encrypted = Column(Text, default="")      # Fernet {"totp": <base32>}
    mfa_recovery_hashes = Column(JSON, default=list)     # sha256 of one-time recovery codes
    auth_provider = Column(String, default="password")   # password | sso
    created_at = Column(DateTime, default=utcnow)

    tenant = relationship("Tenant")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    token_hash = Column(String, unique=True, index=True)  # SHA-256, never raw
    expires_at = Column(DateTime)
    revoked = Column(Integer, default=0)
    user_agent = Column(String, default="")             # session metadata
    ip = Column(String, default="")
    label = Column(String, default="")
    last_used_at = Column(DateTime, nullable=True)
    session_started_at = Column(DateTime, default=utcnow)  # chain origin; survives rotation
    created_at = Column(DateTime, default=utcnow)


class AuditLog(Base):
    """Tamper-evident compliance record of *effected* security-relevant changes.

    Rows are append-only and linked into a per-workspace hash chain
    (``seq`` / ``prev_hash`` / ``entry_hash``, see app.services.audit): altering
    or deleting any row breaks verification from that point on. ``detail`` and
    ``meta`` are encrypted at rest; everything used as a filter key stays
    plaintext.
    """
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, nullable=True, index=True)  # NULL = platform-level
    actor_email = Column(String, default="")
    actor_user_id = Column(Integer, nullable=True, index=True)  # stable; email may change
    actor_role = Column(String, default="")
    action = Column(String, index=True)                  # e.g. auth.login, document.deleted
    target_type = Column(String, default="", index=True)  # document | user | role | tenant | …
    target_id = Column(String, default="", index=True)
    detail = Column(EncryptedText, default="")           # encrypted at rest
    meta = Column(EncryptedJSON, default=dict)           # structured extras, encrypted at rest
    ip = Column(String, default="")
    user_agent = Column(String, default="")
    request_id = Column(String, default="", index=True)  # correlate with observability
    seq = Column(Integer, default=0, index=True)         # per-chain monotonic counter
    prev_hash = Column(String, default="")
    entry_hash = Column(String, default="", index=True)
    created_at = Column(DateTime, default=utcnow, index=True)


class ActivityLog(Base):
    """Behavioural stream — who did what on the platform, including reads.

    Higher volume and lower stakes than the audit log: not hash-chained,
    retention-bounded (``ACTIVITY_RETENTION_DAYS``, trimmed by
    scripts/purge_logs.py). Powers the admin activity explorer and the
    per-user "my activity" view. ``meta`` is encrypted at rest.
    """
    __tablename__ = "activity_log"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    actor_email = Column(String, default="")
    actor_role = Column(String, default="")
    action = Column(String, index=True)                  # session.start | document.retrieved | …
    category = Column(String, default="", index=True)    # read | write | auth | admin | export
    target_type = Column(String, default="", index=True)
    target_id = Column(String, default="", index=True)
    method = Column(String, default="")
    route = Column(String, default="")
    status = Column(Integer, default=0)
    ip = Column(String, default="")
    user_agent = Column(String, default="")
    request_id = Column(String, default="", index=True)
    meta = Column(EncryptedJSON, default=dict)
    created_at = Column(DateTime, default=utcnow, index=True)


class QueryLog(Base):
    __tablename__ = "query_log"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # The Q&A transcript is the most sensitive content in this DB → encrypted.
    question = Column(EncryptedText)
    answer = Column(EncryptedText)
    mode = Column(String, default="llm")                    # llm | extractive | not_found
    confidence = Column(Float, default=0.0)                 # top retrieval score
    latency_ms = Column(Integer, default=0)
    sources_json = Column(EncryptedJSON, default=list)
    filters_json = Column(JSON, default=dict)
    cost_estimate_usd = Column(Float, default=0.0)
    feedback = Column(Integer, nullable=True)               # 1 = helpful, -1 = not helpful
    created_at = Column(DateTime, default=utcnow)


# ── Fine-grained access model ──────────────────────────────────────
# Layered on top of the built-in RBAC matrix (app.rbac). Everything below is
# tenant-scoped. A user with no custom role, grant or group behaves exactly as
# their built-in role — this model is inert until an admin uses it.

class Role(Base):
    """A tenant-defined role: a named bundle of permissions."""
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    key = Column(String, nullable=False)                 # slug, unique per tenant
    name = Column(String, default="")
    description = Column(String, default="")
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_role_tenant_key"),)

    permissions = relationship("RolePermission", cascade="all, delete-orphan",
                               backref="role")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    id = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id"), index=True, nullable=False)
    permission = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("role_id", "permission", name="uq_role_permission"),)


class Group(Base):
    """A named set of users. Roles / grants assigned to a group apply to members."""
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_group_tenant_name"),)

    members = relationship("GroupMember", cascade="all, delete-orphan", backref="group")


class GroupMember(Base):
    __tablename__ = "group_members"
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_member"),)


class PrincipalRole(Base):
    """Assigns a custom Role to a subject (a user or a group)."""
    __tablename__ = "principal_roles"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    subject_type = Column(String, nullable=False)        # user | group
    subject_id = Column(Integer, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("subject_type", "subject_id", "role_id",
                                       name="uq_principal_role"),)


class PermissionGrant(Base):
    """A direct allow/deny override for a subject. deny always wins."""
    __tablename__ = "permission_grants"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    subject_type = Column(String, nullable=False)        # user | group
    subject_id = Column(Integer, nullable=False)
    permission = Column(String, nullable=False)
    effect = Column(String, default=GRANT_ALLOW)         # allow | deny
    note = Column(String, default="")
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("subject_type", "subject_id", "permission",
                                       name="uq_permission_grant"),)


class ResourceGrant(Base):
    """Per-object ACL: <subject> may <permission> on <resource_type:resource_id>.
    Additive only (no deny) and overrides ownership / clearance for that object."""
    __tablename__ = "resource_grants"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    subject_type = Column(String, nullable=False)        # user | group
    subject_id = Column(Integer, nullable=False)
    resource_type = Column(String, nullable=False)       # document | collection
    resource_id = Column(String, nullable=False)         # string for future-proofing
    permission = Column(String, nullable=False)
    granted_by = Column(String, default="")
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("subject_type", "subject_id", "resource_type",
                                       "resource_id", "permission",
                                       name="uq_resource_grant"),)


# ── Authentication: API keys, password history, email tokens, SSO ───

class ApiKey(Base):
    """A named, hashed, optionally-expiring API key for a workspace. Replaces the
    single plaintext ``Tenant.api_key`` (which still works for back-compat)."""
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), index=True, nullable=False)
    name = Column(String, default="")
    prefix = Column(String, index=True)                  # first chars, for display
    key_hash = Column(String, unique=True, index=True)   # sha256 of the full key
    created_by = Column(String, default="")
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    revoked = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)


class PasswordHistory(Base):
    __tablename__ = "password_history"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class AuthToken(Base):
    """Single-use, hashed, time-boxed token emailed to a user."""
    __tablename__ = "auth_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    purpose = Column(String, nullable=False)             # verify_email | reset_password
    token_hash = Column(String, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class SsoConnection(Base):
    """Per-tenant OIDC identity provider (the 'sso' entitlement). Generic OIDC —
    works with Google, Okta, Microsoft Entra, Auth0, Keycloak, …"""
    __tablename__ = "sso_connections"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), unique=True, index=True, nullable=False)
    display_name = Column(String, default="SSO")
    issuer = Column(String, default="")                  # OIDC issuer URL (discovery)
    client_id = Column(String, default="")
    secret_encrypted = Column(Text, default="")          # Fernet {"client_secret": ...}
    allowed_domains = Column(JSON, default=list)         # email domains eligible for JIT
    default_role = Column(String, default="member")
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class SsoState(Base):
    """Short-lived OIDC authorization-flow state (CSRF token + PKCE verifier)."""
    __tablename__ = "sso_states"
    id = Column(Integer, primary_key=True)
    state = Column(String, unique=True, index=True)
    tenant_id = Column(Integer, index=True)
    code_verifier = Column(String, default="")
    redirect_uri = Column(String, default="")
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
    # Fine-grained access: per-user clearance for confidentiality (ABAC).
    _add_column_if_missing("users", "clearance", f"clearance INTEGER DEFAULT {DEFAULT_CLEARANCE}")
    # Authentication hardening
    _add_column_if_missing("users", "email_verified", "email_verified INTEGER DEFAULT 1")
    _add_column_if_missing("users", "mfa_enabled", "mfa_enabled INTEGER DEFAULT 0")
    _add_column_if_missing("users", "mfa_secret_encrypted", "mfa_secret_encrypted TEXT DEFAULT ''")
    _add_column_if_missing("users", "mfa_recovery_hashes", "mfa_recovery_hashes JSON DEFAULT '[]'")
    _add_column_if_missing("users", "auth_provider", "auth_provider VARCHAR DEFAULT 'password'")
    _add_column_if_missing("users", "password_changed_at", "password_changed_at DATETIME")
    _add_column_if_missing("refresh_tokens", "user_agent", "user_agent VARCHAR DEFAULT ''")
    _add_column_if_missing("refresh_tokens", "ip", "ip VARCHAR DEFAULT ''")
    _add_column_if_missing("refresh_tokens", "label", "label VARCHAR DEFAULT ''")
    _add_column_if_missing("refresh_tokens", "last_used_at", "last_used_at DATETIME")
    _add_column_if_missing("refresh_tokens", "session_started_at", "session_started_at DATETIME")
    # Governance: structured + tamper-evident audit trail. Existing rows get
    # seq=0 / empty hashes — verify_chain() treats the first row with a hash as
    # the chain anchor, so a pre-upgrade history simply isn't chained (and is
    # reported as such) rather than failing verification.
    _add_column_if_missing("audit_log", "actor_user_id", "actor_user_id INTEGER")
    _add_column_if_missing("audit_log", "target_type", "target_type VARCHAR DEFAULT ''")
    _add_column_if_missing("audit_log", "target_id", "target_id VARCHAR DEFAULT ''")
    _add_column_if_missing("audit_log", "meta", "meta JSON DEFAULT '{}'")
    _add_column_if_missing("audit_log", "ip", "ip VARCHAR DEFAULT ''")
    _add_column_if_missing("audit_log", "user_agent", "user_agent VARCHAR DEFAULT ''")
    _add_column_if_missing("audit_log", "request_id", "request_id VARCHAR DEFAULT ''")
    _add_column_if_missing("audit_log", "seq", "seq INTEGER DEFAULT 0")
    _add_column_if_missing("audit_log", "prev_hash", "prev_hash VARCHAR DEFAULT ''")
    _add_column_if_missing("audit_log", "entry_hash", "entry_hash VARCHAR DEFAULT ''")
    # Tenant lifecycle. Existing workspaces are active.
    _add_column_if_missing("tenants", "status", "status VARCHAR DEFAULT 'active'")
    _add_column_if_missing("tenants", "suspended_at", "suspended_at DATETIME")
    _add_column_if_missing("tenants", "suspended_reason", "suspended_reason VARCHAR DEFAULT ''")


def new_api_key() -> str:
    return "kd-" + secrets.token_urlsafe(24)
