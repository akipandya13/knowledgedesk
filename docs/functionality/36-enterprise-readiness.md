# Enterprise readiness view

## What it does

A board/demo-friendly summary of whether a workspace is ready to roll out.

## How it works

`GET /api/admin/readiness` returns:

- `rollout_stage` — `demo-ready` if any document is `ready`, else
  `needs-documents`.
- `checks` — capability flags: `multi_tenant_isolation`, `local_llm_default`,
  `citations`, `audit_log`, `bulk_zip_ingestion`, `drive_sharepoint_connectors`
  (`configured` / `stub-ready`).
- `document_status` — `{total, ready, failed}`.
- `usage` — `{queries, knowledge_gaps}`.
- `recommended_next_step` — e.g. "Upload ZIP/Drive export and run 20 pilot
  questions".

## Interfaces

| Method | Path |
|--------|------|
| GET | `/api/admin/readiness` |

UI: the **Rollout readiness** card on `/insights`.

## Permissions

`settings.read` (member and up).

## Source

- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — `enterprise_readiness`

## Related

[Workspace insights](31-workspace-insights.md) · [Workspace settings](27-workspace-settings.md)
