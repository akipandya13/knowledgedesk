# Role-Based Access Control (v1)

This document describes how authorisation works in KnowledgeDesk after the RBAC
pass: a single permission matrix, one enforcement point per route, and a
two-layer document model (personal workspace vs company-wide).

---

## 1. Principals

Every request resolves to a **Principal** — `{role, user?, tenant?}` — in
[`app/auth.py`](../backend/app/auth.py), through one of two doors:

| Door | Who | Tenant comes from |
|------|-----|-------------------|
| `Authorization: Bearer <JWT>` | Human users (`member`, `tenant_admin`, `superadmin`) | The verified token — never the request body |
| `X-API-Key: <tenant key>` | Machine integrations — role `service` | The key → tenant lookup |

Because the tenant is always read from the credential, cross-tenant access is
structurally impossible; no route needs to check it.

---

## 2. The permission matrix

The authoritative model is [`app/rbac.py`](../backend/app/rbac.py). A
**permission** is a capability string; `ROLE_PERMISSIONS` maps each role to the
set it holds. Nothing else in the codebase compares role names or ranks.

| Permission | member | tenant_admin | service | superadmin |
|---|:--:|:--:|:--:|:--:|
| `query.run` | ✅ | ✅ | ✅ | — |
| `feedback.write` | ✅ | ✅ | ✅ | — |
| `document.read` | ✅ | ✅ | ✅ | — |
| `document.write.workspace` — own personal docs | ✅ | ✅ | ✅ | — |
| `document.write.tenant` — company-wide docs + any user's docs | — | ✅ | ✅ | — |
| `insights.read` | ✅ | ✅ | ✅ | — |
| `settings.read` | ✅ | ✅ | ✅ | — |
| `settings.write` | — | ✅ | ✅ | — |
| `model_connector.manage` | — | ✅ | ✅ | — |
| `data_connector.manage` | — | ✅ | ✅ | — |
| `audit.read` (workspace audit log) | — | ✅ | ✅ | — |
| `user.manage` | — | ✅ | — | ✅ |
| `tenant.manage` | — | — | — | ✅ |
| `platform.read` (platform audit + stats) | — | — | — | ✅ |

Design rules baked into the matrix:

* **`member ⊆ tenant_admin`** — an admin can do everything a member can.
* **`service = tenant_admin − user.manage`** — API keys act for a workspace but
  never manage humans.
* **`superadmin` holds no workspace-content permission.** The platform operator
  manages tenants, cross-tenant users, and platform telemetry — it cannot read a
  document or ask a question. Attempts return
  `403 "Platform administrator has no access to workspace content"`.

To move a capability between roles, edit `ROLE_PERMISSIONS` and nothing else.

---

## 3. Enforcement

One helper, used at every protected route:

```python
from app.auth import require, tenant_ctx
from app.rbac import Permission

@router.post("/upload")
def upload(..., principal = Depends(require(Permission.DOC_WRITE_WORKSPACE))): ...

@router.get("/stats")
def stats(..., tenant = Depends(tenant_ctx(Permission.INSIGHTS_READ))): ...
```

* `require(*perms)` → returns the `Principal`; `403` if the role is missing any
  permission, `400` if the route needs a workspace and the principal has none.
* `tenant_ctx(*perms)` → same check, but resolves straight to the `Tenant` so
  existing route bodies that expect `tenant=Depends(...)` are unchanged.

The older names (`require_member`, `require_tenant_admin`, `require_superadmin`,
`require_user_manager`, `get_tenant`) are thin aliases over the same model.

The three drifted copies of an ad-hoc `_require_workspace_admin` helper (which
had quietly re-granted `superadmin` access to connectors and settings) are gone.

---

## 4. The two-layer document model

Documents live in one of two layers within a workspace:

| Layer | `scope` | `owner_user_id` | Visible to | Managed by |
|-------|---------|-----------------|------------|------------|
| **Company-wide** | `tenant` | `NULL` | everyone in the workspace | `tenant_admin` / `service` |
| **Personal workspace** | `workspace` | the owner | the owner + workspace admins | the owner (and admins) |

Behaviour:

* **Upload.** A member's uploads land in their own workspace. An admin's uploads
  are company-wide by default; an admin may also target a specific user's
  workspace (`scope=workspace&owner_user_id=<id>`). A member cannot publish
  company-wide or upload into someone else's workspace (`403`).
* **List** (`GET /api/documents?scope=all|workspace|company`). A member sees
  company-wide docs plus their own; `scope` only narrows that. An admin sees the
  whole workspace and can filter by `owner_user_id`.
* **Delete.** A member can delete a document only if it is in their own
  workspace. An admin can delete anything in the workspace.
* **Connector syncs and the demo seed** produce company-wide documents.
* **De-duplication** (by content hash) is scoped to `(tenant, scope, owner)`, so
  one user's private copy never blocks the company copy or another user's copy.

### Migration

Existing rows get `scope='tenant', owner_user_id=NULL` — i.e. **company-wide** —
so nothing that was visible before disappears. Existing Qdrant points have no
`scope` payload; the retrieval filter treats a missing `scope` as company-wide
(`IsEmpty` clause) and self-heals as documents are re-ingested.

---

## 5. Search scope

`POST /api/query/{ask,ask/stream,search}` accept `scope`:

| `scope` | Searches |
|---------|----------|
| `all` (default) | The caller's personal docs **+** company-wide docs |
| `workspace` | Only the caller's personal docs |
| `company` | Only company-wide docs |

The access filter is built server-side from the verified principal
(`app/services/vectorstore.py :: _access_condition`) and **cannot be widened by
the request** — `scope` can only narrow what the caller is already allowed to
see. One user can never retrieve another user's personal documents.

`QueryLog` now records `user_id`, so per-user history/analytics are possible
later without another migration.

---

## 6. Frontend

[`src/lib/auth/permissions.ts`](../frontend/src/lib/auth/permissions.ts) mirrors
the matrix and exposes `can(user, permission)`. The dashboard route guard
([`(dashboard)/layout.tsx`](../frontend/src/app/(dashboard)/layout.tsx)) and the
sidebar ([`components/Sidebar.tsx`](../frontend/src/components/Sidebar.tsx)) both
derive visibility from `can(...)` instead of hand-maintained route lists. This is
UX only — the backend is always the authority.

The Documents page has an *Everything / My workspace / Company-wide* filter and a
visibility selector on upload (members are locked to their own workspace). The
Ask page has a matching *Search in* selector.

---

## 7. Tests

[`backend/tests/`](../backend/tests) runs the real app through `TestClient` with
the vector store stubbed:

* `test_rbac_matrix.py` — matrix invariants + HTTP-level guard checks
  (member blocked from admin surfaces, superadmin blocked from workspace
  content, service key manages connectors but not users, …).
* `test_document_scope.py` — upload scope resolution, list visibility, delete
  rules, and the retrieval access filter.

```bash
cd backend && pip install -r requirements-dev.txt && pytest
```
