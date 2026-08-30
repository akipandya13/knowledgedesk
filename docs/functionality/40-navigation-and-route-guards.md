# Navigation & route guards

## What it does

Shows each user only the pages they can use, and redirects away from pages they
cannot — driven by the same permission names as the backend.

## How it works

- `lib/auth/permissions.ts` mirrors `backend/app/rbac.py`: a role→permission map
  and `can(user, permission)`.
- **Route guard** — `(dashboard)/layout.tsx` maps each route prefix to a required
  permission (`ROUTE_PERMISSION`). On navigation it:
  1. redirects unauthenticated users to `/login?next=...`;
  2. redirects `force_password_change` users to `/change-password`;
  3. redirects to the role's home if `can(user, routePerm)` is false.
- **Sidebar** — one `SECTIONS` list (Platform / Workspace / Administration /
  Account); each item carries a `perm` and is hidden unless `can(user, perm)`.
  Empty sections disappear.
- `ROLE_HOME` decides the landing route per role (`superadmin` →
  `/platform/overview`, everyone else → `/ask`).

This is UX only. The backend independently enforces every permission, so a
hand-crafted request to a hidden route still `403`s.

| Route prefix | Permission |
|--------------|-----------|
| `/ask`, `/history` | `query.run` |
| `/documents`, `/collections` | `document.read` |
| `/insights` | `insights.read` |
| `/users` | `user.manage` |
| `/audit` | `audit.read` |
| `/connectors` | `data_connector.manage` |
| `/model-connectors` | `model_connector.manage` |
| `/settings` | `settings.write` |
| `/platform/**` | `platform.read` |
| `/change-password` | always allowed |

## Source

- [`frontend/src/lib/auth/permissions.ts`](../../frontend/src/lib/auth/permissions.ts)
- [`frontend/src/app/(dashboard)/layout.tsx`](../../frontend/src/app/(dashboard)/layout.tsx)
- [`frontend/src/components/Sidebar.tsx`](../../frontend/src/components/Sidebar.tsx)
- [`frontend/src/lib/config.ts`](../../frontend/src/lib/config.ts) — `ROLE_HOME`

## Related

[Roles & permissions](03-roles-and-permissions.md) · [Web client architecture](39-web-client-architecture.md)
