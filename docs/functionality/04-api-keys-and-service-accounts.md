# API keys / service accounts

> Superseded for new keys by **hashed, named, multi-key, expiring** API keys —
> see [Session & API-key management](45-session-and-api-key-management.md). The
> single plaintext `Tenant.api_key` described below still works.

## What it does

Gives machine integrations a way to call the API on behalf of one workspace,
without a human login.

## How it works

- Each tenant has one `api_key` (`kd-<random>`), created with the tenant and
  visible to superadmins in the platform workspace list.
- A request presenting `X-API-Key: <key>` (or the legacy `X-Tenant-Key`) resolves
  to a Principal with role `service`, `user = None`, and `tenant` = the key's
  tenant.
- `service` holds every `tenant_admin` permission **except** `user.manage` — it
  can ingest documents, run queries, manage connectors and change settings, but
  cannot create or modify user accounts.
- Because `user` is `None`, a service caller has no personal document workspace:
  its uploads must be company-wide, and its searches only see company-wide
  documents.

## Interfaces

Any `/api/*` route that accepts a workspace principal. Send the header instead of
`Authorization: Bearer`.

## Permissions

Role `service` — see the matrix in [`../RBAC_V1.md`](../RBAC_V1.md).

## Configuration

`DEMO_TENANT_API_KEY` seeds the demo tenant's key. New tenants get a random key
from `new_api_key()`.

## Source

- [`backend/app/auth.py`](../../backend/app/auth.py) — door 2 in `get_principal`
- [`backend/app/database.py`](../../backend/app/database.py) — `Tenant.api_key`, `new_api_key`

## Related

[Authentication](01-authentication.md) ·
[Multi-tenancy & workspaces](05-multi-tenancy-and-workspaces.md) ·
[Document scope](09-document-scope.md)
