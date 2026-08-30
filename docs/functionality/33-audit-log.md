# Audit log

## What it does

Records every security-relevant event — who did what, when — at both workspace
and platform level.

## What is recorded

Logins (success and failure, plus refresh-token reuse detection), logout,
password changes/resets, user lifecycle, tenant lifecycle, document deletion,
settings changes, connector create/update/delete/sync.

Each `AuditLog` row: `tenant_id` (NULL = platform-level), `actor_email`,
`actor_role`, `action` (e.g. `auth.login`, `user.created`,
`tenant.model_settings_changed`), `detail`, `created_at`. Audit writes never
break the request path — a failed write is logged and swallowed.

## Interfaces

| Method | Path | Scope |
|--------|------|-------|
| GET | `/api/admin/audit?limit=` | current workspace only |
| GET | `/api/admin/platform/audit?limit=` | all workspaces + platform events |

UI: `/audit` (workspace admin), `/platform/audit` (superadmin).

## Permissions

- `/api/admin/audit` → `audit.read` (tenant_admin, service). Superadmin has no
  access to a workspace's audit log.
- `/api/admin/platform/audit` → `platform.read` (superadmin only).

## Source

- [`backend/app/services/audit.py`](../../backend/app/services/audit.py) — `record`
- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — `tenant_audit`, `platform_audit`
- [`backend/app/database.py`](../../backend/app/database.py) — `AuditLog`

## Related

[Platform administration](34-platform-administration.md) · [User management](06-user-management.md)
