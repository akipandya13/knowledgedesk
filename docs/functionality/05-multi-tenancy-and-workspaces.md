# Multi-tenancy & workspaces

## What it does

Runs many isolated customer workspaces (tenants) on one deployment. One user's
questions, documents, settings, connectors and audit trail never cross into
another workspace.

## How it works

- A **Tenant** has a `slug` (used in Qdrant collection names), a display `name`,
  an `api_key`, and a `settings_json` blob of per-workspace overrides.
- Isolation is **structural, not a filter you can forget**: the tenant is read
  from the verified JWT/API key, never from the request. Every DB query is
  scoped by `tenant_id`; vector data lives in per-tenant Qdrant collections
  (`kd_<slug>_<provider>_<model>`).
- **Provisioning** is superadmin-only. Creating a tenant returns its API key.
  Deleting a tenant drops its Qdrant collections and removes its users and query
  log.
- Bootstrap: on first startup a `superadmin` account is created; if
  `DEMO_TENANT_ENABLED` is set, a `demo` tenant (and optionally demo users) is
  created too.

## Interfaces

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/admin/tenants` | create a workspace → returns API key |
| GET | `/api/admin/tenants` | list workspaces with user/doc counts |
| DELETE | `/api/admin/tenants/{slug}` | delete a workspace + its data |

UI: `/platform/workspaces` (superadmin).

## Permissions

`tenant.manage` (superadmin only).

## Configuration

`DEMO_TENANT_ENABLED`, `DEMO_TENANT_API_KEY`, `DEMO_USERS_ENABLED`,
`SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD`.

## Source

- [`backend/app/database.py`](../../backend/app/database.py) — `Tenant`
- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — tenant lifecycle
- [`backend/app/main.py`](../../backend/app/main.py) — `_bootstrap_db`
- [`backend/app/services/vectorstore.py`](../../backend/app/services/vectorstore.py) — per-tenant collections

## Related

[Platform administration](34-platform-administration.md) ·
[Workspace settings](27-workspace-settings.md) ·
[API keys / service accounts](04-api-keys-and-service-accounts.md)
