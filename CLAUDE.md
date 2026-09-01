# CLAUDE.md — working in this repo

Guidance for the next Claude session. Read this before making changes.

---

## 1. What this is

**KnowledgeDesk** — a multi-tenant internal knowledge assistant. Upload company
documents, ask natural-language questions, get grounded answers with citations.

- **backend/** — FastAPI (Python 3.12), SQLite for metadata, Qdrant for vectors,
  pluggable LLM/embedding backends (Ollama local by default).
- **frontend/** — Next.js 15 (App Router, React 19), standalone build, proxies
  `/api/*` to the backend.
- **docker-compose.yml** — `qdrant`, `ollama`, `ollama-init`, `app`, `web`.

Deep reference already written — **use it, keep it current**:

- [`docs/functionality/`](docs/functionality/) — one file per capability (49 +
  index). If you add or change a feature, update the matching file.
- [`docs/RBAC_V1.md`](docs/RBAC_V1.md) — the authorisation + document-scope model.
- [`docs/FINE_GRAINED_RBAC.md`](docs/FINE_GRAINED_RBAC.md) — custom roles, groups,
  grants, resource ACLs and clearance, layered on RBAC_V1.
- [`docs/OBSERVABILITY.md`](docs/OBSERVABILITY.md) — the metrics/events/traces
  architecture and how to add a sink.
- [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) — the two records (tamper-evident
  `audit_log` hash chain + behavioural `activity_log`), how to add coverage,
  chain verification, retention (`scripts/purge_logs.py`).
- [`docs/TENANCY.md`](docs/TENANCY.md) — isolation layers, the organization
  lifecycle (provision/configure/suspend/delete), `Tenant.status`,
  `TENANT_SCOPED_MODELS`, entitlements.
- [`docs/AUTHENTICATION.md`](docs/AUTHENTICATION.md) — login/MFA/SSO/sessions/
  API-keys/password-policy and the `sso` subscription entitlement.
- [`docs/DEPLOYMENT_TLS.md`](docs/DEPLOYMENT_TLS.md) — Caddy TLS termination,
  forwarded headers, `PUBLIC_BASE_URL`.
- [`docs/ENCRYPTION_AT_REST.md`](docs/ENCRYPTION_AT_REST.md) — envelope KEK/DEK,
  encrypted columns + Qdrant payloads, rotation, `reencrypt_at_rest.py`.
- [`docs/SECRETS_MANAGEMENT.md`](docs/SECRETS_MANAGEMENT.md) — `${provider:locator}`
  references, pluggable providers, where each secret is resolved.
- [`docs/`](docs/) — older `*_FIX.md` notes on specific incidents.

---

## 2. Architecture map

```
backend/app/
  main.py            app wiring, startup bootstrap, /api/health, /api/demo/seed, SPA fallback
  config.py          Settings (pydantic-settings) — every env var lives here
  database.py        SQLAlchemy models + init_db() migrations + role/scope constants
  rbac.py            Permission constants + ROLE_PERMISSIONS matrix (pure data)
  auth.py            get_principal, require(), tenant_ctx(), legacy guard aliases
  security.py        bcrypt, JWT, refresh tokens, lockout, TOTP, email tokens, api-key hashing, pw policy
  authn.py           login rate-limiter, transactional email, entitlements, OIDC client
  crypto.py          envelope encryption at rest: KEK/DEK, EncryptedText/JSON, secret bundles
  secret_resolver.py pluggable ${provider:locator} secret resolution (env/file/vault/awssm/…)
  request_context.py per-request ip / user-agent / request-id capture (governance)
  activity_middleware.py  one activity_log row per authenticated API call
  model_catalog.py   model profiles + connector provider field specs (static)
  tenant_settings.py effective_settings / resolve_model_config / embedding_locked
  observability/     signal facade + pluggable sinks (metrics/events/traces)
  routers/           thin HTTP layer — auth_routes, users, documents, query, admin, connectors, observability
  services/          the actual work:
    ingestion.py     validate → dedup → queue; parse → chunk → embed → upsert
    parsers.py       per-format text extraction
    chunking.py      sentence-aware chunking
    embeddings.py    local + remote embedding backends, heavy-model guard
    vectorstore.py   Qdrant: per-tenant collections, search + access filter
    reranker.py      optional cross-encoder, best-effort
    rag.py           retrieve → rerank → ground → answer (+ streaming), query logging
    llm.py           ollama / openai_compatible / azure_foundry / bedrock / none
    audit.py         audit.record() + hash-chained verify_chain() (tamper-evident)
    activity.py      activity.record() — behavioural stream (reads + writes), retention-bounded
    tenants.py       organization lifecycle: set_status (suspend/reactivate), purge_tenant_data, tenant_detail
    connectors/      gdrive.py, sharepoint.py, base.py

frontend/src/
  lib/api/           one module per route group; client.ts adds token + refresh-on-401
  lib/auth/          AuthProvider (context), tokenStore, permissions.ts (can())
  lib/types.ts       response shapes mirrored from the backend
  app/(dashboard)/   authed pages; layout.tsx is the route guard
  components/        Sidebar, TopBar, Modal, ui.tsx primitives
```

---

## 3. Running & testing

### Run the stack

```bash
docker compose up -d            # first run builds; qdrant+ollama pull
curl localhost:8000/api/health  # app/qdrant/llm status
open http://localhost:3000      # web client
```

Default accounts: see [`DEFAULT_USERS_AND_PASSWORDS.md`](DEFAULT_USERS_AND_PASSWORDS.md).

### ⚠️ Restart vs rebuild

`app` and `web` have **no source bind-mount** — code is baked into the image at
build time. After editing backend or frontend code:

```bash
docker compose up -d --build app web     # NOT `docker compose restart`
```

`docker compose restart` only re-runs the existing image and will silently ignore
your changes. Volumes (`app_data`, `qdrant_data`) persist across rebuilds, so the
SQLite DB and vectors survive.

### Backend tests

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

`backend/tests/` runs the real FastAPI app through `TestClient` with
`qdrant_client` stubbed and ingestion neutralised (`conftest.py`). No services
needed.

> The machine's system/anaconda Python is **broken** (`import starlette` fails
> despite fastapi being installed). Do not try to run the app or tests against
> it — use a fresh venv from `requirements-dev.txt`, or run inside the `app`
> container (`docker compose exec app pytest` after adding the dev dep there).

### Frontend checks

```bash
cd frontend
npm install
npx tsc --noEmit        # must be clean
```

There is no ESLint config committed; `next lint` will prompt interactively —
skip it. `tsc` is the gate.

---

## 4. Conventions to follow

### Authorization — never hand-roll it

- Every protected route uses `Depends(require(Permission.X))` or
  `Depends(tenant_ctx(Permission.X))` from `app/auth.py`. **Do not** write
  `if principal.role == "tenant_admin"` or compare `ROLE_RANK`.
- To add/move a **built-in** capability: edit `ROLE_PERMISSIONS` in
  [`backend/app/rbac.py`](backend/app/rbac.py) — one place — and mirror the
  change in [`frontend/src/lib/auth/permissions.ts`](frontend/src/lib/auth/permissions.ts).
- Per-request effective perms (`principal.perms`) fold in **custom roles + grants**
  from [`backend/app/authz.py`](backend/app/authz.py). `require()` reads that set.
  For object-scoped checks use `authz.can_on(db, principal, perm, type, id)`, not
  a bare `require()`. See [`docs/FINE_GRAINED_RBAC.md`](docs/FINE_GRAINED_RBAC.md).
- New permission string? add it to `Permission`, decide its built-in role
  membership, add a `PERMISSION_DESCRIPTIONS` entry, keep it out of
  `PLATFORM_PERMISSIONS` unless it truly is platform-only, and mirror in
  `permissions.ts`.
- New frontend page? add its prefix→permission row in
  `frontend/src/app/(dashboard)/layout.tsx` and a nav entry with a `perm` in
  `Sidebar.tsx`. Gate UI with the auth context's `hasPermission()` (reflects
  grants), not the pure `can(user, …)`.
- `superadmin` must never gain a workspace-content permission. `service` (API
  key) must never gain `user.manage`.

### Tenant & user identity come from the token, never the request

`get_principal` resolves `{role, user, tenant}` from the verified JWT or API key.
Route bodies read `principal.tenant` / `principal.user_id`. Never accept a
tenant id, user id, or `scope` widening from the request body/query as
authoritative. `get_principal` also refuses a `Tenant.status != 'active'`
workspace with 403 (superadmin exempt) — so suspension needs no per-route work.
Superadmin-only org lifecycle lives in `services/tenants.py` +
`routers/admin.py` (`/api/admin/tenants…`); see [`docs/TENANCY.md`](docs/TENANCY.md).
When you add a tenant-scoped table, add it to `TENANT_SCOPED_MODELS` so
`purge_tenant_data` cleans it on workspace deletion.

### Document scope

Two layers: `scope='tenant'` (company-wide, `owner_user_id=NULL`) and
`scope='workspace'` (personal, owned). See [`docs/RBAC_V1.md`](docs/RBAC_V1.md).
When touching documents or retrieval:

- Dedup key is `(tenant_id, scope, owner_user_id, content_hash)`.
- The retrieval access filter is built **server-side** in
  `vectorstore._access_condition` from the principal — keep it that way.
- Connector syncs and the demo seed create company-wide docs only.

### Database migrations

SQLite. `init_db()` in `database.py` calls `_add_column_if_missing(table, col,
ddl)` for every column added after v1. Migrations are **additive only** — no
drops, no type changes, no non-null-without-default. Add the column to the model
*and* an `_add_column_if_missing` line, and give existing rows a sensible default.

### Routers thin, logic in services

Routers validate input, call a service, shape the response. Business logic,
external calls, and multi-step flows live in `app/services/`.

### Model configuration

Never read `get_settings()` fields directly for RAG behaviour. Go through
`tenant_settings.resolve_model_config(tenant)` (or `effective_settings`) so
profile + per-workspace overrides + selected connector are all applied.
Respect `embedding_locked(tenant, db)` before changing embedding config.

### Secrets & encryption at rest

Connector / MFA / SSO credentials are always `crypto.encrypt_secrets(...)` /
`decrypt_secrets(...)` (KEK-level). API responses expose only `secret_fields_set`
(names), never values. `""` clears a field, omitted leaves it.

For **stored content** use the DEK layer: the `EncryptedText` / `EncryptedJSON`
column types (already on `query_log` + `audit_log`) or `crypto.encrypt/decrypt`
directly (Qdrant chunk text, obs sink). Ciphertext is tagged `kdenc:` and
`decrypt` passes legacy plaintext through — so adding encryption to a column
needs no migration, but run `scripts/reencrypt_at_rest.py` to backfill. Never
encrypt a column that is filtered/joined in SQL or used as a Qdrant filter key
(emails, filenames, department, confidentiality). See
[`docs/ENCRYPTION_AT_REST.md`](docs/ENCRYPTION_AT_REST.md).

When you add a new secret setting, pass it through `secret_resolver.resolve_secret()`
at the point of use (not at `Settings` construction — resolution can hit a
network backend and must stay lazy). Stored connector/SSO secrets are already
covered via `crypto.decrypt_secrets(token, resolve=True)` on the runtime path.
See [`docs/SECRETS_MANAGEMENT.md`](docs/SECRETS_MANAGEMENT.md).

### Audit & activity (governance)

Two records, complementary — see [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md):

- **Audit** (`audit_log`, tamper-evident, hash-chained): call
  `audit.record(db, action="area.verb_past", principal=principal,
  target_type="document", target_id=doc.id, changes=audit.diff(before, after),
  detail=...)` on every security-relevant mutation. `principal=` back-fills
  actor/tenant (and API-key id/name); `changes={field:[old,new]}` records
  data-modification history (goes in `meta`, hash-covered; `audit.diff` masks
  secret fields). Rows are serialised + SHA-256-chained per workspace inside the
  service; never write `AuditLog` by hand. `GET /api/admin/audit/verify` checks
  the chain; `…/audit/history?target_type=&target_id=` is the per-entity timeline.
- **Activity** (`activity_log`, behavioural, retention-bounded): the
  `ActivityMiddleware` already logs one row per authenticated API call. Add an
  explicit `activity.record(db, action="session.start", category="auth",
  principal=principal, target_type=..., target_id=...)` only where the firehose
  can't infer intent (sessions, `document.retrieved`, exports).
- Neither call may raise into the request path (both swallow + log).
- New governance read surface → gate with `Permission.AUDIT_READ` /
  `Permission.ACTIVITY_READ`, mirror in `permissions.ts`.
- Retention is manual: `scripts/purge_logs.py` (`ACTIVITY_RETENTION_DAYS` /
  `AUDIT_RETENTION_DAYS`).

### Authentication

Login is a two-step flow (password → optional TOTP). New sessions go through
`auth_routes.mint_session` / `_issue_session` so refresh tokens carry device
metadata, `session_started_at` (chain origin), and the concurrent-session cap —
don't create `RefreshToken` rows by hand. Session lifetime (idle / absolute /
concurrent) is enforced across rotation in `refresh()`; keep `session_started_at`
carried forward. Subscription-gated features
check `authn.entitlement_enabled(tenant, "<name>")` and return `402` when off;
add new gated features to `authn.KNOWN_ENTITLEMENTS`. Transactional email always
goes through `authn.send_email` (pluggable; `console` in dev). MFA/SSO secrets
use `crypto.encrypt_secrets`. Full map: [`docs/AUTHENTICATION.md`](docs/AUTHENTICATION.md).

### Observability

Emit signals through the facade only: `from app import observability as obs`,
then `obs.count(...)`, `obs.gauge(...)`, `obs.observe(...)` (histogram),
`obs.event(kind, **fields)`, `with obs.span(name): ...`. Never import a
monitoring vendor's client into app code — new backends are **sinks**
(`app/observability/sinks/`, register in `SINK_BUILDERS`; see
[`docs/OBSERVABILITY.md`](docs/OBSERVABILITY.md)). Every call is a no-op when
disabled and must never raise into the request path. Audit is the compliance
record; observability events are the ops stream — they are complementary, keep
both.

### Laptop-safe mode

`LAPTOP_SAFE_MODE` (default true) + the heavy-model guards in `embeddings.py` /
`reranker.py` exist so a demo box never triggers a multi-GB download mid-query.
If you add a model or profile, classify it in `model_catalog.py`
(`HEAVY_LOCAL_MODELS` / `LARGE_OLLAMA_MODELS` / `SAFE_DEMO_OLLAMA_MODELS`) and
make failures degrade gracefully (extractive answer), not 500.

### Code style (match what's there)

- Module docstrings explain **why**, not just what — often with a short "Design
  notes" block. Match that density; don't add ceremony to trivial files.
- `from __future__ import annotations` at the top of backend modules.
- Type hints everywhere; `dataclass` for small value objects (`Principal`,
  `Chunk`).
- Frontend: functional components, hooks, `type` imports, no default-export
  utils. File references in prose use `[text](path)` markdown links, not
  backticks.
- Keep comments at the altitude of the surrounding file.

---

## 5. Known gotchas

- **`docker compose restart` doesn't apply code changes** — rebuild (see §3).
- **System Python is broken** — use a venv or the container.
- **Qdrant collection names embed the embedding model**
  (`kd_<slug>_<provider>_<model>`); switching embeddings orphans vectors — hence
  the embedding lock.
- `@app.on_event("startup")` deprecation warnings in test output are
  pre-existing; leave unless you're deliberately migrating to lifespan handlers.
- The demo seed reads `/app/sample_docs` (compose bind-mount) — absent outside
  Docker.
- `backend/requirements.txt` pins heavy ML deps (torch, sentence-transformers);
  a full `pip install` is slow. Tests only need `requirements-dev.txt`.

---

## 6. Definition of done for a change

1. `cd frontend && npx tsc --noEmit` is clean (if frontend touched).
2. `cd backend && .venv/bin/pytest` is green; add/extend a test for new
   behaviour (`backend/tests/`).
3. Permission changes mirrored in `rbac.py` **and** `permissions.ts`.
4. Security-relevant mutations call `audit.record`; notable domain actions also
   `obs.event(...)`.
5. DB columns added via model + `_add_column_if_missing`, with a default for
   existing rows.
6. The matching [`docs/functionality/`](docs/functionality/) file is updated (and
   [`docs/RBAC_V1.md`](docs/RBAC_V1.md) if authz/scope changed).
7. If backend or frontend code changed and you're verifying live:
   `docker compose up -d --build app web`.
8. Don't commit or push unless asked; if asked, branch first (never commit to
   `main` directly).
