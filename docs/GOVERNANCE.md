# Governance — audit trail & user activity tracking

KnowledgeDesk keeps **two** first-class records of what happens in a workspace,
because they answer different questions and have opposite requirements.

| | Audit log | User activity log |
|--|-----------|-------------------|
| Question | "What security-relevant change was *made*, by whom?" | "What has this *person been doing*?" |
| Table | `audit_log` | `activity_log` |
| Contents | effected mutations only | mutations **and reads** (sessions, retrievals, page views, exports) |
| Integrity | append-only, **per-workspace SHA-256 hash chain**, `…/verify` endpoint | best-effort, not chained |
| Volume | low | high (one row per authenticated API call) |
| Retention | `AUDIT_RETENTION_DAYS` = `0` (keep forever) | `ACTIVITY_RETENTION_DAYS` = `90` |
| Encrypted at rest | `detail`, `meta` | `meta` |
| Read | `GET /api/admin/audit` (`audit.read`) | `GET /api/admin/activity` (`activity.read`), `GET /api/me/activity` (self) |
| UI | `/audit`, `/platform/audit` | `/activity`, `/security` → "My recent activity" |

Full detail: [functionality/33-audit-log.md](functionality/33-audit-log.md) and
[functionality/50-user-activity-tracking.md](functionality/50-user-activity-tracking.md).
Denied *attempts* (not effected changes) live on the observability event stream —
[functionality/49-security-event-logging.md](functionality/49-security-event-logging.md).

## How the pieces fit

```
request ─▶ RequestContextMiddleware   capture ip / user-agent / request-id  (app/request_context.py)
        ─▶ ObservabilityMiddleware    metrics + ops events
        ─▶ get_principal              resolves identity, stashes scope["kd_actor"]
        ─▶ handler                    audit.record(...) on security mutations
        ◀─ ActivityMiddleware         one activity_log row per authenticated call
```

- **`audit.record(db, *, action, principal=…, target_type=…, target_id=…,
  changes=…, meta=…, detail=…)`** — call on every security-relevant mutation.
  `principal=` back-fills actor/tenant (and, for an API-key principal, the key
  id/name into `meta`); `changes={field: [old, new]}` (build it with
  **`audit.diff(before, after)`**, which auto-masks secret-looking fields)
  records a data-modification-history entry — stored in `meta["changes"]` so it
  is encrypted *and* hash-covered. Serialised + hash-chained inside the service.
- **`activity.record(db, *, action, category, principal=… | user_id/tenant_id,
  target_type=…, target_id=…, meta=…)`** — call at semantically interesting
  points the request firehose can't infer (`session.start`, `document.retrieved`,
  exports). Everything else is captured automatically by `ActivityMiddleware`.
- Neither call may raise into the request path — both swallow and log on failure.

## Data-modification history

Any mutation that carries `changes=` is queryable as a per-entity timeline:

```
GET /api/admin/audit/history?target_type=user&target_id=42
```

→ every audit entry naming that target, newest first, each with its
`{field: [old, new]}` change-set. Covered today: `user` (role / name / clearance
/ active), `workspace_settings`, `model_connector`, `data_connector`, `role`
(permission set), `grant:*` (allow↔deny), `confidentiality_policy`,
`auth_policy`, `api_key`. Secret fields show as `["***", "***"]` — the rotation
is recorded, the value is not. UI: **History** button on each row of `/users`,
and `/audit?target_type=…&target_id=…`.

## Actor identification

Human actions record `actor_email` + stable `actor_user_id` + `actor_role` +
`ip` / `user_agent` / `request_id`. **API-key actions** record
`actor = "api-key:<name>"` and `meta.api_key_id` / `meta.api_key_name`, so a
machine action is tied to a specific, revocable key rather than an anonymous
`"api-key"`.

## Administrative vs. content activity

`ActivityMiddleware` tags a write to an admin control-plane surface
(`/api/admin/*`, `/api/access/*`, `/api/users*`, `/api/connectors*`,
`/api/sso/*`, `/api/observability/*`) with `category="admin"` instead of
`"write"`, so "administrative activity" is one filter:
`GET /api/admin/activity?category=admin`.

## Verifying the audit chain

```
GET /api/admin/audit/verify                     # this workspace
GET /api/admin/platform/audit/verify            # every chain (superadmin)
GET /api/admin/platform/audit/verify?tenant_id= # one chain
```

Returns `{ok, checked, unchained, truncated, chains[], first_broken}`.
`unchained` = pre-upgrade rows; `truncated` = a retention purge trimmed a
prefix (both benign). `ok:false` with `first_broken` = a row was edited or
deleted.

## Retention

Retention is **manual and opt-in** so a compliance record is never lost to a
background job:

```
docker compose exec app python -m scripts.purge_logs --dry-run
docker compose exec app python -m scripts.purge_logs --yes
```

Windows come from `ACTIVITY_RETENTION_DAYS` / `AUDIT_RETENTION_DAYS`
(override per-run with `--activity-days` / `--audit-days`). `AUDIT_RETENTION_DAYS`
must be set `> 0` for the audit log to be trimmed at all.

## Adding coverage

- New security mutation → add an `audit.record(...)` with `action`,
  `target_type`/`target_id`, `principal=`. Pick a dotted `action` name
  (`area.verb_past`).
- New meaningful user action the firehose mislabels → add an
  `activity.record(...)` with a friendly `action` and `category`.
- New governance read surface → gate with `Permission.ACTIVITY_READ` or
  `Permission.AUDIT_READ`; mirror any permission change in
  [`frontend/src/lib/auth/permissions.ts`](../frontend/src/lib/auth/permissions.ts).
