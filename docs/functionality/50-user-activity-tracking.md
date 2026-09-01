# User activity tracking

## What it does

Records **what each person does on the platform** — including *reads* — as a
behavioural stream that sits alongside the audit log. Where the
[audit log](33-audit-log.md) is the tamper-evident record of *effected security
changes*, the activity log answers "what has this user been doing": sessions
started/ended, documents their questions retrieved, admin surfaces they opened,
data they exported.

It is deliberately cheaper than the audit log — no hash chain, retention-bounded,
every write best-effort.

## What is recorded

**The request firehose** — one row per authenticated API call (method, route
template, status), from a middleware. `category` is `read` for GET/HEAD,
`write` for other methods, and **`admin`** when the write targets a control-plane
surface (`/api/admin/*`, `/api/access/*`, `/api/users*`, `/api/connectors*`,
`/api/sso/*`, `/api/observability/*`) — so administrative activity is one
filter. Anonymous requests, `GET /api/health`, `/metrics`, CORS pre-flight,
token refresh and `GET /api/me/activity` are skipped. Toggle with
`ACTIVITY_LOG_REQUESTS`. API-key callers are recorded as
`actor = "api-key:<name>"` with `meta.api_key_id`.

**Semantic events** — added by handlers where the firehose can't infer intent:

| action | when |
|--------|------|
| `session.start` / `session.end` | login (password or MFA) / logout, with `meta.mfa` |
| `document.retrieved` | one per distinct document a question actually surfaced content from (`target_type=document`) |
| `export.audit` / `export.activity` | a CSV export was taken |
| `<method>:<route>` | every other authenticated call (firehose) |

Each `ActivityLog` row: `tenant_id`, `user_id`, `actor_email`, `actor_role`,
`action`, `category`, `target_type`/`target_id`, `method`/`route`/`status`,
`ip`/`user_agent`/`request_id`, `meta` (**encrypted at rest**), `created_at`.

## Retention

`ACTIVITY_RETENTION_DAYS` (default `90`), trimmed by
[`scripts/purge_logs.py`](../../backend/scripts/purge_logs.py) when an operator
runs it (never automatic).

## Interfaces

| Method | Path | Scope |
|--------|------|-------|
| GET | `/api/admin/activity` | current workspace — the explorer |
| GET | `/api/admin/platform/activity` | all workspaces (superadmin) |
| GET | `/api/me/activity` | **the caller's own rows only** |

List params: `user_id` (per-person timeline), `prefix`, `action`, `category`,
`actor`, `target_type`, `target_id`, `since`, `until`, `before_id` (cursor),
`limit`, `format=csv`. `/api/me/activity` takes `action_prefix`, `category`,
`since`, `until`, `before_id`, `limit` and is always pinned to
`principal.user_id`.

UI:

- `/activity` (workspace admin) — filter by user / category / action / date,
  cursor paging, CSV export. `?user=<id>` deep-links a per-person view.
- `/security` → **My recent activity** — the self-service transparency panel any
  signed-in user sees about their own account.

## Permissions

- `/api/admin/activity` → `activity.read` (tenant_admin, service). Superadmin
  has no access to a workspace's activity log.
- `/api/admin/platform/activity` → `platform.read` (superadmin only).
- `/api/me/activity` → any authenticated workspace principal (own rows only).

## Configuration

| env | default | effect |
|-----|---------|--------|
| `ACTIVITY_LOG_ENABLED` | `true` | master switch for all activity writes |
| `ACTIVITY_LOG_REQUESTS` | `true` | the per-request firehose (semantic events still fire when off) |
| `ACTIVITY_RETENTION_DAYS` | `90` | window applied by `purge_logs.py` |
| `TRUST_FORWARDED_FOR` | `true` | derive client IP from `X-Forwarded-For` (behind Caddy) |

## Source

- [`backend/app/services/activity.py`](../../backend/app/services/activity.py) — `record`, `list_entries`, `purge`
- [`backend/app/activity_middleware.py`](../../backend/app/activity_middleware.py) — the firehose
- [`backend/app/request_context.py`](../../backend/app/request_context.py) — IP / UA / request-id capture
- [`backend/app/routers/me.py`](../../backend/app/routers/me.py) — self-service view
- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — admin + platform explorers
- [`backend/app/services/rag.py`](../../backend/app/services/rag.py) — `document.retrieved`
- [`backend/app/database.py`](../../backend/app/database.py) — `ActivityLog`
- [`backend/tests/test_governance.py`](../../backend/tests/test_governance.py)

## Related

[Audit log](33-audit-log.md) · [Security event logging](49-security-event-logging.md) ·
[Observability](41-observability.md) · [Query history](32-query-history.md)
