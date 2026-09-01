# Platform administration

## What it does

The superadmin's cross-workspace control plane: workspace lifecycle,
platform-wide user view, platform audit, and platform stats. It deliberately has
**no** access to any workspace's document content or Q&A.

## Capabilities

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/admin/tenants` | create a workspace (+ optional first admin, entitlements) → API key |
| GET | `/api/admin/tenants` | list workspaces with status + user/doc counts + keys |
| GET | `/api/admin/tenants/{slug}` | one workspace: status, counts, entitlements, overrides |
| PATCH | `/api/admin/tenants/{slug}` | rename / set entitlements (audited with a diff) |
| POST | `/api/admin/tenants/{slug}/suspend` | lock the workspace (`{reason?}`) + revoke live sessions |
| POST | `/api/admin/tenants/{slug}/reactivate` | restore access |
| DELETE | `/api/admin/tenants/{slug}` | delete a workspace + **every** tenant-scoped table + vectors |
| GET | `/api/admin/platform/audit?limit=` | audit across all workspaces + platform events |
| GET | `/api/admin/platform/activity?limit=` | activity across all workspaces |
| GET | `/api/admin/platform/audit/verify` | verify one or every workspace's hash chain |
| GET | `/api/admin/platform/stats` | tenant / user / document / query totals |
| GET/POST/PATCH | `/api/users` (with `tenant_slug`) | manage users in any workspace + other superadmins |

UI: `/platform/overview`, `/platform/workspaces`, `/platform/users`,
`/platform/audit`.

## Permissions

`tenant.manage` and `platform.read` (superadmin only); `user.manage` for the
user endpoints. A superadmin calling any workspace-content route
(`/api/documents`, `/api/query/*`, `/api/admin/stats`, connectors, settings)
gets `403 "Platform administrator has no access to workspace content"`.

## Configuration

`SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD` (bootstrap, forced change on first
login). Legacy `ADMIN_API_KEY` still works for the deprecated `X-Admin-Key`
scripts path.

## Source

- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — tenant + platform endpoints
- [`backend/app/routers/users.py`](../../backend/app/routers/users.py)
- [`frontend/src/app/(dashboard)/platform/`](../../frontend/src/app/(dashboard)/platform/)

## Related

[Multi-tenancy & workspaces](05-multi-tenancy-and-workspaces.md) ·
[Roles & permissions](03-roles-and-permissions.md) · [Audit log](33-audit-log.md)
