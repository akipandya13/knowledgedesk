# Multi-tenancy & workspaces

## What it does

Runs many isolated customer workspaces (tenants) on one deployment. One user's
questions, documents, settings, connectors and audit trail never cross into
another workspace.

## How it works

- A **Tenant** has a `slug` (used in Qdrant collection names), a display `name`,
  an `api_key`, a `settings_json` blob of per-workspace overrides, and a
  lifecycle `status` (`active` | `suspended`).
- Isolation is **structural, not a filter you can forget**: the tenant is read
  from the verified JWT/API key, never from the request (`get_principal`). Every
  DB query is scoped by `tenant_id`; vector data lives in per-tenant Qdrant
  collections (`kd_<slug>_<provider>_<model>`); the retrieval access filter is
  built server-side from the principal.
- **Tenant-aware authorization**: `require()` / `tenant_ctx()` enforce
  `principal.tenant` *and* the permission; `principal.perms` is resolved
  per-request from *that* tenant's custom roles + grants; `superadmin` holds no
  workspace-content permission and platform permissions can't enter a tenant
  role.
- **Lifecycle** (superadmin only):
  - *Provision* — create a workspace, optionally with its first `tenant_admin`
    (`admin_email` → one-time password in the response), and initial
    entitlements.
  - *Configure* — rename, grant/revoke subscription entitlements (`sso`, …).
  - *Suspend / reactivate* — `status='suspended'` makes `get_principal` (and
    login / refresh) refuse every credential for the workspace with `403`,
    and revokes live sessions. No data is touched; reactivating restores access.
    `superadmin` is unaffected.
  - *Delete* — `app.services.tenants.purge_tenant_data` sweeps **every**
    tenant-scoped table (documents, connectors, API keys, roles/groups/grants,
    refresh tokens, audit + activity logs, SSO) and drops the Qdrant
    collections; the row tally is returned and written into the platform audit
    entry.
- Bootstrap: on first startup a `superadmin` account is created; if
  `DEMO_TENANT_ENABLED` is set, a `demo` tenant (and optionally demo users) is
  created too.

## Interfaces

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/admin/tenants` | create a workspace (+ optional first admin, entitlements) → returns API key |
| GET | `/api/admin/tenants` | list workspaces with status + user/doc counts |
| GET | `/api/admin/tenants/{slug}` | one workspace: status, counts, entitlements, overrides |
| PATCH | `/api/admin/tenants/{slug}` | rename, set entitlements (audited with a diff) |
| POST | `/api/admin/tenants/{slug}/suspend` | lock the workspace (`{reason?}`), revoke sessions |
| POST | `/api/admin/tenants/{slug}/reactivate` | restore access |
| DELETE | `/api/admin/tenants/{slug}` | delete a workspace + **all** its data |

UI: `/platform/workspaces` (superadmin) — status badge, Manage (rename +
entitlements), Suspend/Reactivate, Delete.

## Permissions

`tenant.manage` (superadmin only).

## Configuration

`DEMO_TENANT_ENABLED`, `DEMO_TENANT_API_KEY`, `DEMO_USERS_ENABLED`,
`SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD`.

## Source

- [`backend/app/database.py`](../../backend/app/database.py) — `Tenant` (+ `status`)
- [`backend/app/auth.py`](../../backend/app/auth.py) — tenant resolution + suspended-tenant refusal
- [`backend/app/services/tenants.py`](../../backend/app/services/tenants.py) — `set_status`, `purge_tenant_data`, `tenant_detail`
- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — tenant lifecycle routes
- [`backend/app/main.py`](../../backend/app/main.py) — `_bootstrap_db`
- [`backend/app/services/vectorstore.py`](../../backend/app/services/vectorstore.py) — per-tenant collections
- [`backend/tests/test_tenancy.py`](../../backend/tests/test_tenancy.py)

## Related

[Platform administration](34-platform-administration.md) ·
[Workspace settings](27-workspace-settings.md) ·
[API keys / service accounts](04-api-keys-and-service-accounts.md)
