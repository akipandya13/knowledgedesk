# Roles & permissions (RBAC)

## What it does

Decides what each caller may do, from a single permission matrix rather than
scattered role checks.

## How it works

Every request resolves to a **Principal** `{role, user?, tenant?}`. A
**permission** is a capability string (`document.write.tenant`);
`ROLE_PERMISSIONS` maps each role to the set it holds. Routes declare the
permission they need via `require(Permission.X)` / `tenant_ctx(Permission.X)`.

| Role | Summary |
|------|---------|
| `member` | Ask, read the shared document list, manage own personal documents, read workspace insights |
| `tenant_admin` | Everything a member can + company-wide documents, users, settings, connectors, workspace audit — own workspace only |
| `service` (API key) | `tenant_admin` minus `user.manage` |
| `superadmin` | Tenants, cross-tenant users, platform audit/stats. **No** workspace-content permission |

Baked-in rules: `member ⊆ tenant_admin`; `service = tenant_admin − user.manage`;
`superadmin` holds zero workspace permissions (a content request returns
`403 "Platform administrator has no access to workspace content"`).

## Interfaces

Not an endpoint — an enforcement layer applied to every `/api/*` route. See each
capability page's **Permissions** section.

## Permissions

Full matrix and the two-layer document rules: [`../RBAC_V1.md`](../RBAC_V1.md).

## Configuration

None. To move a capability between roles, edit `ROLE_PERMISSIONS`.

## Source

- [`backend/app/rbac.py`](../../backend/app/rbac.py) — permissions + matrix
- [`backend/app/auth.py`](../../backend/app/auth.py) — `require`, `tenant_ctx`, aliases
- [`frontend/src/lib/auth/permissions.ts`](../../frontend/src/lib/auth/permissions.ts) — client mirror (`can()`)
- [`backend/tests/test_rbac_matrix.py`](../../backend/tests/test_rbac_matrix.py)

## Related

[Navigation & route guards](40-navigation-and-route-guards.md) ·
[Document scope](09-document-scope.md) ·
[User management](06-user-management.md)
