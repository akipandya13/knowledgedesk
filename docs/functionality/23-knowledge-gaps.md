# Knowledge gaps

## What it does

Records every question the knowledge base could not answer, so admins know which
documents to add.

## How it works

- When retrieval returns no hits above the score threshold, the answer is the
  standard not-found message and the query is logged with `mode="not_found"`.
- `GET /api/admin/gaps` returns recent not-found questions with timestamps.
- `/insights` shows a **Knowledge gaps** panel (latest 10) and a
  **knowledge_gaps** count tile; `/api/admin/readiness` includes the total.

## Interfaces

| Method | Path |
|--------|------|
| GET | `/api/admin/gaps?limit=` |

UI: `/insights`.

## Permissions

`insights.read` (member / tenant_admin / service).

## Source

- [`backend/app/services/rag.py`](../../backend/app/services/rag.py) — not-found path in `answer` / `answer_stream`
- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — `knowledge_gaps`

## Related

[Workspace insights](31-workspace-insights.md) · [Query history](32-query-history.md)
