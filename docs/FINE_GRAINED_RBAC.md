# Fine-grained access control

Layered on top of the built-in RBAC matrix ([`RBAC_V1.md`](RBAC_V1.md)). The
built-in four roles still define the baseline; this adds **custom roles,
groups, per-subject allow/deny grants, per-object ACLs and clearance-based
(ABAC) confidentiality filtering**. All of it is tenant-scoped and **inert until
an admin uses it** — a user with no custom role/grant/group resolves to exactly
`ROLE_PERMISSIONS[user.role]`.

---

## 1. Effective permissions

For a user **U** in their workspace ([`app/authz.py`](../backend/app/authz.py)):

```
effective(U) =
      builtin(U.role)                         # member | tenant_admin | service | superadmin
   ∪  permissions of every custom Role assigned to U or a Group U belongs to
   ∪  direct 'allow' PermissionGrants for U or its groups
   −  direct 'deny'  PermissionGrants for U or its groups        ← deny always wins
```

Resolved **once per request** in `get_principal` and stored on
`principal.perms`; `require(Permission.X)` and `principal.can(X)` check that set.
If resolution ever fails it degrades to the built-in matrix (never 500s).

**New permissions:** `document.delete` (grantable per-object) and
`access.manage` (administer this whole model). `tenant.manage` / `platform.read`
can never be put in a tenant role or grant.

---

## 2. Resource ACLs (per-object)

`ResourceGrant(subject, resource_type, resource_id, permission)` — additive, no
deny. `authz.can_on(db, principal, perm, type, id)` is:

```
perm ∈ effective(U)                         # a global capability covers it
OR a matching ResourceGrant for U or its groups
```

Wired in:

| Where | Effect of a grant |
|-------|-------------------|
| `GET /api/documents` | a `document.read` grant makes that one doc visible regardless of scope / ownership / clearance |
| `DELETE /api/documents/{id}` | a `document.delete` grant lets a non-owner delete that one doc |
| retrieval (`/api/query/*`) | granted doc ids are added to the server-side access filter as an extra `should` clause |

`resource_type` ∈ `{document, collection}`; grantable permissions are
`document.read`, `document.write.workspace`, `document.delete`.

---

## 3. Groups

`Group` + `GroupMember`. A custom role or a grant assigned to a group applies to
every member (`subject_type = "group"`). Deleting a group cascades its
memberships, role assignments and grants.

---

## 4. Clearance (ABAC — opt-in)

Per-tenant switch `settings_json.confidentiality_enforced` (via
`PUT /api/access/policy`). Each user has `User.clearance` (default 100 = sees
everything). Document `confidentiality` maps to a level:

| value | level |
|-------|-------|
| public | 10 |
| internal | 20 |
| confidential | 30 |
| restricted | 40 |
| _(unknown)_ | 99 |

When enforced, a user sees a document only if `level(confidentiality) ≤
clearance` — **unless** they own it, hold `document.write.tenant`, or have a
`document.read` ResourceGrant. Enforced in the document list **and** in
retrieval (`vectorstore._access_conditions` adds a `confidentiality ∈ allowed`
MUST-clause that own/shared docs bypass). Off by default → the field stays pure
metadata.

---

## 5. Admin API — `/api/access/*` (needs `access.manage`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/catalog` | assignable permissions + descriptions + confidentiality levels |
| GET | `/me` | **any workspace principal** — caller's effective perms, custom roles, groups, clearance |
| GET | `/effective/{user_id}` | computed effective set for a user |
| GET/POST | `/roles` · PATCH/DELETE `/roles/{id}` | custom roles |
| GET/POST | `/groups` · DELETE `/groups/{id}` · POST/DELETE `/groups/{id}/members[/{uid}]` | groups |
| GET | `/assignments?subject_type=&subject_id=` | a subject's roles + grants |
| POST | `/role-assignments` · DELETE `/role-assignments/{id}` | assign a custom role to user/group |
| POST | `/grants` · DELETE `/grants/{id}` | allow/deny a permission for user/group |
| GET/POST | `/resource-grants` · DELETE `/resource-grants/{id}` | per-object ACLs |
| GET/PUT | `/policy` | confidentiality enforcement toggle |

Clearance is set via the existing `PATCH /api/users/{id}` with `{clearance}`
(also requires `access.manage`). Every mutation writes an [audit](functionality/33-audit-log.md) entry (`access.*`).

Guard rails: a platform permission in a role/grant → 400; denying your own
`access.manage` → 400; every subject/role must belong to the caller's tenant.

---

## 6. Frontend

- `/api/access/me` is folded into the auth context
  ([`AuthProvider`](../frontend/src/lib/auth/AuthProvider.tsx)) as
  `hasPermission(...)`; the route guard and sidebar use it, so a user granted a
  capability via a custom role sees the corresponding nav immediately.
- **Access control** page (`/access`, needs `access.manage`): tabs for custom
  roles, groups, per-user roles/grants/clearance, and the confidentiality
  policy toggle.

---

## 7. Source & tests

- [`backend/app/authz.py`](../backend/app/authz.py) — the resolver (`effective_permissions`, `can_on`, `granted_resource_ids`, clearance, `retrieval_access`)
- [`backend/app/routers/access.py`](../backend/app/routers/access.py) — CRUD + validation + audit
- [`backend/app/database.py`](../backend/app/database.py) — `Role`, `RolePermission`, `Group`, `GroupMember`, `PrincipalRole`, `PermissionGrant`, `ResourceGrant`, `User.clearance`
- wiring: `auth.py` (`_resolve_perms`), `routers/documents.py`, `routers/query.py`, `services/vectorstore.py`
- [`backend/tests/test_authz.py`](../backend/tests/test_authz.py) — 14 tests (custom role, deny precedence, groups, resource read/delete, clearance, overrides, lock-out guard)

## Extending further

The `subject_type` column is already `user | group`; add `service_account` or
`api_key` there for keyed integrations. `resource_type` is open-ended — add
`connector`, `setting`, etc. For time-bound access, add `expires_at` to
`PermissionGrant` / `ResourceGrant` and filter on it in `authz`.
