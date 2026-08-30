# Query history

## What it does

A running log of every question asked in a workspace, with how it was answered.

## How it works

- Every Ask / stream / search-backed answer writes a `QueryLog` row: `tenant_id`,
  `user_id`, `question`, `answer`, `mode`, `confidence`, `latency_ms`,
  `sources_json`, `filters_json`, `feedback`, `created_at`.
- `GET /api/admin/queries?limit=` returns the most recent rows (id, question,
  mode, confidence, latency, feedback, timestamp).
- The `/history` page renders this table for the whole workspace. `user_id` was
  added with the RBAC document-scope work, so per-user history is available to
  build on without another migration.

## Interfaces

| Method | Path |
|--------|------|
| GET | `/api/admin/queries?limit=` |

UI: `/history` (member-visible) and the "Recent questions" table on `/insights`.

## Permissions

`insights.read` (member / tenant_admin / service).

## Source

- [`backend/app/services/rag.py`](../../backend/app/services/rag.py) — `_log`
- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — `recent_queries`
- [`frontend/src/app/(dashboard)/history/page.tsx`](../../frontend/src/app/(dashboard)/history/page.tsx)

## Related

[Workspace insights](31-workspace-insights.md) · [Answer feedback](22-answer-feedback.md)
