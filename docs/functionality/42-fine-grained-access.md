# Fine-grained access control

## What it does

Extends the four built-in roles with **custom roles, groups, per-subject
allow/deny grants, per-object ACLs, and clearance-based confidentiality
filtering** — all tenant-scoped and administered from the app. Inert until an
admin uses it: a user with no custom config behaves exactly as their base role.

## How it works

- **Effective permissions** = `builtin(role) ∪ custom roles (of the user or its
  groups) ∪ 'allow' grants − 'deny' grants` (**deny wins**). Resolved once per
  request ([`app/authz.py`](../../backend/app/authz.py)) onto `principal.perms`;
  `require(Permission.X)` checks that.
- **Groups** — a role or grant on a group applies to every member.
- **Resource ACLs** — `ResourceGrant(subject, type, id, permission)`; wired into
  document list, document delete, and retrieval (granted doc ids widen the
  server-side access filter). Grantable: `document.read`,
  `document.write.workspace`, `document.delete`.
- **Clearance (ABAC)** — opt-in per tenant (`PUT /api/access/policy`). Each user
  has a `clearance`; a document is hidden if its `confidentiality` level exceeds
  it, unless owned / admin / explicitly shared. Off by default.
- New permissions: `document.delete`, `access.manage`. Platform permissions can
  never be assigned in a tenant role/grant.

## Interfaces

`/api/access/*` (all need `access.manage`, except `/me` = any workspace user):
`catalog`, `me`, `effective/{id}`, `roles`, `groups` (+ `/members`),
`assignments`, `role-assignments`, `grants`, `resource-grants`, `policy`.
Clearance via `PATCH /api/users/{id}` `{clearance}`.

UI: **Access control** page (`/access`) — roles, groups, per-user
roles/grants/clearance, policy toggle. The auth context exposes `hasPermission()`
from `/api/access/me` so nav reflects granted capabilities.

## Permissions

`access.manage` — `tenant_admin` and `service` by default (not `superadmin`,
which is platform-scoped; not `member`).

## Configuration

`settings_json.confidentiality_enforced` per tenant (default false). No env vars.

## Source

- [`backend/app/authz.py`](../../backend/app/authz.py), [`backend/app/routers/access.py`](../../backend/app/routers/access.py)
- [`backend/app/database.py`](../../backend/app/database.py) — 7 new tables + `User.clearance`
- [`backend/tests/test_authz.py`](../../backend/tests/test_authz.py)
- [`frontend/src/app/(dashboard)/access/page.tsx`](../../frontend/src/app/(dashboard)/access/page.tsx)
- Deep dive: [`../FINE_GRAINED_RBAC.md`](../FINE_GRAINED_RBAC.md)

## Related

[Roles & permissions](03-roles-and-permissions.md) · [Document scope](09-document-scope.md) ·
[User management](06-user-management.md) · [Audit log](33-audit-log.md)
