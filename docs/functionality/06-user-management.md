# User management

## What it does

Create, list, update, disable and reset users — scoped so a workspace admin only
ever touches their own workspace, while a superadmin manages any workspace and
other platform admins.

## How it works

- **Scope resolution** (`_scope_tenant`): a `tenant_admin` always operates on
  their own tenant (any tenant identifier in the request is ignored). A
  `superadmin` passes `tenant_slug` explicitly, or omits it to manage other
  superadmins.
- **Create** — email is validated and lowercased; a temporary password is
  generated if none is supplied (returned once as `temporary_password`); the new
  user starts with `force_password_change=1`. A `tenant_admin` may only create
  `member` / `tenant_admin` roles.
- **Update** — change name, role, or active state. Safety rails: you cannot
  disable your own account, you cannot demote the last active admin of a
  workspace, and a `tenant_admin` cannot see or touch users outside their tenant
  (returns 404).
- **Disable** revokes the user's refresh tokens immediately.
- **Reset password** — see [Password management](02-password-management.md).
- Every action writes an [audit](33-audit-log.md) entry.

## Interfaces

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/users?tenant=<slug>` | list users in scope |
| POST | `/api/users` | create a user |
| PATCH | `/api/users/{id}` | update name / role / active |
| POST | `/api/users/{id}/reset-password` | issue a temp password |

UI: `/users` (workspace admin), `/platform/users` (superadmin).

## Permissions

`user.manage` — held by `tenant_admin` (own workspace) and `superadmin`. **Not**
held by `service` API keys.

## Configuration

None beyond the bootstrap accounts.

## Source

- [`backend/app/routers/users.py`](../../backend/app/routers/users.py)
- [`frontend/src/app/(dashboard)/users/page.tsx`](../../frontend/src/app/(dashboard)/users/page.tsx)

## Related

[Roles & permissions](03-roles-and-permissions.md) ·
[Password management](02-password-management.md) ·
[Audit log](33-audit-log.md)
