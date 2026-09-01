# Multi-tenancy & the organization lifecycle

One deployment, many isolated customer **workspaces** (tenants / organizations).
This is the map; per-capability detail is in
[functionality/05-multi-tenancy-and-workspaces.md](functionality/05-multi-tenancy-and-workspaces.md).

## Isolation — structural, not a filter you can forget

| Layer | Mechanism |
|-------|-----------|
| Identity | `get_principal` reads `{role, user, tenant}` from the **verified JWT / API key** — never from the request body, query or a header the caller controls. |
| Relational data | every tenant-scoped table carries `tenant_id`; every query filters on `principal.tenant.id`. Dedup key is `(tenant_id, scope, owner_user_id, content_hash)`. |
| Vectors | one Qdrant collection per `(tenant, embedding model)` — `kd_<slug>_<provider>_<model>`. `vectorstore._access_condition` builds the read filter server-side from the principal. |
| Authorization | `require()` / `tenant_ctx()` enforce `principal.tenant` **and** the permission; `principal.perms` folds in *that tenant's* custom roles + grants. `superadmin` holds no workspace-content permission; `PLATFORM_PERMISSIONS` can never enter a tenant role/grant. |
| Suspension | `Tenant.status != 'active'` → `get_principal`, `/auth/login` and `/auth/refresh` refuse every workspace credential with `403` (superadmin exempt). |

`backend/tests/test_tenancy.py::test_cross_tenant_data_is_invisible` is the
regression guard.

## Lifecycle (superadmin, `tenant.manage`)

```
POST   /api/admin/tenants                     provision (+ optional first admin, entitlements)
GET    /api/admin/tenants                     list — status + counts
GET    /api/admin/tenants/{slug}              detail — status, counts, entitlements, overrides
PATCH  /api/admin/tenants/{slug}              rename / set entitlements   (audited, with a diff)
POST   /api/admin/tenants/{slug}/suspend      {reason?} — lock + revoke live sessions
POST   /api/admin/tenants/{slug}/reactivate   restore
DELETE /api/admin/tenants/{slug}              purge everything + drop collections
```

Every lifecycle action writes a **platform-chain** audit entry
(`tenant.created|updated|suspended|reactivated|deleted`, `tenant_id=NULL`,
`target_type="tenant"`, with `changes` / a `rows_deleted` tally in `meta`).

### Provisioning the first admin

`POST /api/admin/tenants` with `admin_email` creates a `tenant_admin` User with
`force_password_change=1` and returns a one-time `temporary_password`. Without
it, a new workspace has no way in until someone `POST /api/users` with
`tenant_slug`.

### Suspend vs delete

- **Suspend** is reversible and lossless — only `status`, `suspended_at`,
  `suspended_reason` change, plus every refresh token for the workspace's users
  is revoked. Access tokens (stateless, ≤30 min) stop working on their next
  request because `get_principal` re-checks status live.
- **Delete** is exhaustive. `app.services.tenants.purge_tenant_data` walks
  `TENANT_SCOPED_MODELS` (keep it in sync when adding a tenant-scoped table),
  removes users + their refresh tokens, and drops the Qdrant collections. The
  per-table tally is returned and audited.

## Tenant configuration

- **Workspace-level** (workspace admin): model / RAG settings, auth policy,
  confidentiality policy, custom roles, connectors — all in
  `tenant.settings_json` via `/api/admin/settings` and `/api/access/*`.
- **Platform-level** (superadmin): subscription **entitlements**
  (`authn.KNOWN_ENTITLEMENTS`, currently `sso`) via
  `PATCH /api/admin/tenants/{slug}`. `entitlement_enabled(tenant, name)` is
  `true` when the name is in the global `ENTITLEMENTS` env **or** the tenant's
  `settings_json["entitlements"]`.

## Adding a tenant-scoped table

1. Add `tenant_id` (FK, indexed) to the model + an `_add_column_if_missing` line
   if it post-dates v1.
2. Add the model to `TENANT_SCOPED_MODELS` in
   [`backend/app/services/tenants.py`](../backend/app/services/tenants.py) so
   `purge_tenant_data` cleans it (rows keyed indirectly — via a role/group id —
   need a special branch there).
3. Filter every query by `principal.tenant.id`; never accept a tenant id from
   the request.
