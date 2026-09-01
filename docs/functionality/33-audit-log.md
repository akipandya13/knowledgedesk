# Audit log

## What it does

Records every security-relevant event that *effected* a change — who did what,
when — at both workspace and platform level, as a **tamper-evident** append-only
record.

## What is recorded

Logins (success and failure, plus refresh-token reuse detection), logout,
password changes/resets, MFA changes, user lifecycle, tenant lifecycle, all
fine-grained access changes (roles, groups, grants, API keys, SSO, auth policy),
connector create/update/delete/sync, model/settings changes, **document upload
and deletion**, and audit/activity CSV exports.

Each `AuditLog` row:

| field | notes |
|-------|-------|
| `tenant_id` | NULL = platform-level |
| `actor_email`, `actor_user_id`, `actor_role` | `actor_user_id` is stable across email changes |
| `action` | dotted, e.g. `auth.login`, `document.deleted`, `access.grant_set` |
| `target_type`, `target_id` | structured subject, e.g. `document` / `42` — queryable |
| `detail` | free-text summary, **encrypted at rest** |
| `meta` | structured extras (JSON), **encrypted at rest** — holds `changes` and, for API-key actors, `api_key_id` / `api_key_name` |
| `changes` (in `meta`) | `{field: [old, new]}` data-modification history; secret fields masked `["***","***"]` |
| `ip`, `user_agent`, `request_id` | captured at the edge; `request_id` correlates with observability |
| `seq`, `prev_hash`, `entry_hash` | the hash chain (below) |
| `created_at` | |

Audit writes never break the request path — a failed write is logged and
swallowed.

## Tamper-evidence (hash chain)

Rows are linked into a **per-workspace hash chain** (`tenant_id IS NULL` events
share chain key `0`):

```
entry_hash = SHA-256( prev_hash || canonical_json(seq, tenant_id, actor,
                                                   action, target, detail,
                                                   meta, created_at) )
```

`prev_hash` of row *n* is `entry_hash` of row *n − 1*. Editing or deleting any
row makes every later row fail verification. A process-wide lock serialises
"read last row → hash → insert" so concurrent writers cannot fork a chain
(sufficient for the single SQLite writer; a multi-writer deployment would move
this to a DB sequence + row lock).

`GET /api/admin/audit/verify` recomputes the whole chain and returns
`{ok, checked, unchained, truncated, chains[], first_broken}`:

- `unchained` — pre-upgrade rows written before the chain existed (not a failure).
- `truncated` — a retention purge trimmed a chain's prefix (`seq` gap; not a
  failure — the remaining rows still verify against each other).
- `first_broken` — the first row whose recomputed hash or predecessor link does
  not match.

## Retention

`AUDIT_RETENTION_DAYS` (default `0` = keep forever). Enforced **only** when an
operator runs [`scripts/purge_logs.py`](../../backend/scripts/purge_logs.py) —
nothing is deleted automatically.

## Interfaces

| Method | Path | Scope |
|--------|------|-------|
| GET | `/api/admin/audit` | current workspace |
| GET | `/api/admin/audit/verify` | current workspace — chain integrity |
| GET | `/api/admin/audit/history?target_type=&target_id=` | one entity's change timeline |
| GET | `/api/admin/platform/audit` | all workspaces + platform events |
| GET | `/api/admin/platform/audit/verify` | one or every chain |

Query params on the list endpoints: `prefix` (action prefix), `action`,
`actor` (substring), `target_type`, `target_id`, `since`, `until` (ISO-8601),
`before_id` (cursor), `limit`, `format=csv`. `format=csv` streams the filtered
rows as an attachment and is itself recorded (`audit.exported` + an
`export.audit` activity event). Platform endpoints also accept `tenant_id`.

UI: `/audit` (workspace admin) — filter bar, **Verify integrity** button, **Export
CSV**, per-row change diff, cursor paging; `/audit?target_type=…&target_id=…` and
the **History** button on `/users` rows open an entity timeline.
`/platform/audit` (superadmin).

## Permissions

- `/api/admin/audit*` → `audit.read` (tenant_admin, service). Superadmin has no
  access to a workspace's audit log.
- `/api/admin/platform/audit*` → `platform.read` (superadmin only).

## Source

- [`backend/app/services/audit.py`](../../backend/app/services/audit.py) — `record`, `diff`, `verify_chain`, `list_entries`
- [`backend/app/request_context.py`](../../backend/app/request_context.py) — IP / UA / request-id capture
- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — read + verify + export routes
- [`backend/app/database.py`](../../backend/app/database.py) — `AuditLog`
- [`backend/scripts/purge_logs.py`](../../backend/scripts/purge_logs.py) — retention
- [`backend/tests/test_governance.py`](../../backend/tests/test_governance.py)

## Related

[User activity tracking](50-user-activity-tracking.md) ·
[Security event logging](49-security-event-logging.md) ·
[Platform administration](34-platform-administration.md) ·
[Encryption at rest](47-encryption-at-rest.md)
