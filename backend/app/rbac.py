"""Role-based access control — the single source of truth for who can do what.

Every protected route declares the *permission* it needs (``require(Permission.X)``
in ``app.auth``); nothing anywhere compares role names or role ranks directly.
Adding a role, or moving a capability between roles, is a one-line edit to the
``ROLE_PERMISSIONS`` matrix below and nothing else.

Roles
  member        Asks questions, manages documents in their own workspace, reads
                the shared document list and workspace insights.
  tenant_admin  Everything a member can, plus company-wide documents, user
                management, settings, connectors and the audit log — for their
                own workspace only.
  superadmin    Platform operator: tenant lifecycle, cross-tenant users,
                platform audit and stats. Deliberately holds NO workspace-content
                permission — it cannot read documents or ask questions.
  service       ``X-API-Key`` principal for machine integrations. tenant_admin
                level content access, but cannot manage users.

This module is pure data (no FastAPI imports) so it can be imported anywhere,
including tests, without pulling in the web stack.
"""
from __future__ import annotations

from .database import (ROLE_MEMBER, ROLE_SERVICE, ROLE_SUPERADMIN,
                       ROLE_TENANT_ADMIN)


class Permission:
    """Capability strings. Grouped by area; the value is what gets logged."""

    # Ask / search
    QUERY_RUN = "query.run"
    FEEDBACK_WRITE = "feedback.write"

    # Documents
    DOC_READ = "document.read"
    DOC_WRITE_WORKSPACE = "document.write.workspace"   # own private workspace docs
    DOC_WRITE_TENANT = "document.write.tenant"          # company-wide docs + any user's docs
    DOC_DELETE = "document.delete"                      # resource-grantable delete

    # Workspace administration
    INSIGHTS_READ = "insights.read"
    SETTINGS_READ = "settings.read"
    SETTINGS_WRITE = "settings.write"
    MODEL_CONNECTOR_MANAGE = "model_connector.manage"
    DATA_CONNECTOR_MANAGE = "data_connector.manage"
    AUDIT_READ = "audit.read"
    OBSERVABILITY_READ = "observability.read"   # metrics / events / traces
    ACCESS_MANAGE = "access.manage"             # custom roles, groups, grants, clearance
    USER_MANAGE = "user.manage"

    # Platform (superadmin)
    TENANT_MANAGE = "tenant.manage"
    PLATFORM_READ = "platform.read"


ALL_PERMISSIONS: frozenset[str] = frozenset(
    v for k, v in vars(Permission).items() if not k.startswith("_") and isinstance(v, str)
)

# Permissions that only ever apply inside a workspace. Used to give superadmin a
# clearer 403 ("no access to workspace content") instead of a bare "missing
# permission".
WORKSPACE_PERMISSIONS: frozenset[str] = frozenset({
    Permission.QUERY_RUN, Permission.FEEDBACK_WRITE,
    Permission.DOC_READ, Permission.DOC_WRITE_WORKSPACE, Permission.DOC_WRITE_TENANT,
    Permission.DOC_DELETE,
    Permission.INSIGHTS_READ, Permission.SETTINGS_READ, Permission.SETTINGS_WRITE,
    Permission.MODEL_CONNECTOR_MANAGE, Permission.DATA_CONNECTOR_MANAGE,
    Permission.AUDIT_READ, Permission.ACCESS_MANAGE,
})

# Permissions that make sense as a per-object grant (app.authz.can_on).
RESOURCE_PERMISSIONS: frozenset[str] = frozenset({
    Permission.DOC_READ, Permission.DOC_WRITE_WORKSPACE, Permission.DOC_DELETE,
})

# Platform permissions may never be put into a tenant custom role or grant.
PLATFORM_PERMISSIONS: frozenset[str] = frozenset({
    Permission.TENANT_MANAGE, Permission.PLATFORM_READ,
})
#: What a tenant custom role / grant is allowed to contain.
ASSIGNABLE_PERMISSIONS: frozenset[str] = frozenset(ALL_PERMISSIONS) - PLATFORM_PERMISSIONS

PERMISSION_DESCRIPTIONS: dict[str, str] = {
    Permission.QUERY_RUN: "Ask questions and run searches",
    Permission.FEEDBACK_WRITE: "Rate answers",
    Permission.DOC_READ: "See the document list and search results",
    Permission.DOC_WRITE_WORKSPACE: "Upload / delete documents in own workspace",
    Permission.DOC_WRITE_TENANT: "Publish company-wide docs; manage any user's docs",
    Permission.DOC_DELETE: "Delete a document (grantable per-object)",
    Permission.INSIGHTS_READ: "View workspace insights and query history",
    Permission.SETTINGS_READ: "View the workspace model/RAG configuration",
    Permission.SETTINGS_WRITE: "Change workspace model/RAG settings",
    Permission.MODEL_CONNECTOR_MANAGE: "Manage LLM / embedding connectors",
    Permission.DATA_CONNECTOR_MANAGE: "Manage Drive / SharePoint connectors",
    Permission.AUDIT_READ: "Read the workspace audit log",
    Permission.OBSERVABILITY_READ: "Read metrics, events and traces",
    Permission.ACCESS_MANAGE: "Manage custom roles, groups, grants and clearance",
    Permission.USER_MANAGE: "Create and manage users",
    Permission.TENANT_MANAGE: "Platform: manage workspaces",
    Permission.PLATFORM_READ: "Platform: read platform audit and stats",
}


# ── The matrix ──────────────────────────────────────────────────────

_MEMBER: set[str] = {
    Permission.QUERY_RUN,
    Permission.FEEDBACK_WRITE,
    Permission.DOC_READ,
    Permission.DOC_WRITE_WORKSPACE,
    Permission.INSIGHTS_READ,
    Permission.SETTINGS_READ,
}

_TENANT_ADMIN: set[str] = _MEMBER | {
    Permission.DOC_WRITE_TENANT,
    Permission.DOC_DELETE,
    Permission.SETTINGS_WRITE,
    Permission.MODEL_CONNECTOR_MANAGE,
    Permission.DATA_CONNECTOR_MANAGE,
    Permission.AUDIT_READ,
    Permission.OBSERVABILITY_READ,
    Permission.ACCESS_MANAGE,
    Permission.USER_MANAGE,
}

# API keys act for a workspace but must never manage humans.
_SERVICE: set[str] = _TENANT_ADMIN - {Permission.USER_MANAGE}

# Platform operator: no workspace-content permissions, but does get the
# operational telemetry it needs to run the platform.
_SUPERADMIN: set[str] = {
    Permission.OBSERVABILITY_READ,
    Permission.USER_MANAGE,
    Permission.TENANT_MANAGE,
    Permission.PLATFORM_READ,
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    ROLE_MEMBER: frozenset(_MEMBER),
    ROLE_TENANT_ADMIN: frozenset(_TENANT_ADMIN),
    ROLE_SERVICE: frozenset(_SERVICE),
    ROLE_SUPERADMIN: frozenset(_SUPERADMIN),
}


def permissions_for(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


def missing_permissions(role: str, needed) -> set[str]:
    """The subset of ``needed`` that ``role`` does NOT hold."""
    return set(needed) - ROLE_PERMISSIONS.get(role, frozenset())
