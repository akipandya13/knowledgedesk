# Document scope — personal vs company-wide

## What it does

Splits every workspace's documents into two layers so an individual can keep
working files private while admins publish shared knowledge.

| Layer | `scope` | `owner_user_id` | Visible to | Managed by |
|-------|---------|-----------------|------------|------------|
| **Company-wide** | `tenant` | `NULL` | everyone in the workspace | `tenant_admin` / `service` |
| **Personal workspace** | `workspace` | the owner | the owner + workspace admins | the owner (+ admins) |

## How it works

- **Upload target.** A member's uploads default to their own workspace. An
  admin's uploads default to company-wide; an admin may also target a specific
  user (`scope=workspace&owner_user_id=<id>`). A member cannot publish
  company-wide or upload into someone else's workspace (`403`).
- **Listing** (`GET /api/documents?scope=all|workspace|company`): a member sees
  company-wide docs **plus** their own; `scope` only narrows. An admin sees the
  whole workspace and can filter by `owner_user_id`.
- **Delete**: a member can delete only documents in their own workspace; an admin
  can delete anything in the workspace.
- **De-duplication** is scoped to `(tenant, scope, owner)` — one user's private
  copy never blocks the company copy or another user's copy.
- **Connector syncs and the demo seed** always produce company-wide documents.
- **Search** honours the same boundary — see [Search scope](19-search-scope.md).

## Migration

Documents that existed before this model get `scope='tenant', owner_user_id=NULL`
(company-wide) so nothing that was visible disappears. Vector points with no
`scope` payload are treated as company-wide and self-heal on re-ingest.

## Permissions

`document.read` to list; `document.write.workspace` for personal writes;
`document.write.tenant` for company-wide writes or acting on another user's docs.

## Source

- [`backend/app/database.py`](../../backend/app/database.py) — `Document.scope`, `Document.owner_user_id`
- [`backend/app/routers/documents.py`](../../backend/app/routers/documents.py) — `_resolve_target`, visibility filter
- [`backend/app/services/vectorstore.py`](../../backend/app/services/vectorstore.py) — `_access_condition`
- [`backend/tests/test_document_scope.py`](../../backend/tests/test_document_scope.py)

## Related

[Search scope](19-search-scope.md) · [Roles & permissions](03-roles-and-permissions.md) ·
[`../RBAC_V1.md`](../RBAC_V1.md)
