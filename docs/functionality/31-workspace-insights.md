# Workspace insights

## What it does

A single dashboard of adoption, answer quality and knowledge gaps for one
workspace.

## Metrics (`GET /api/admin/stats`)

`documents_total`, `documents_ready`, `documents_failed`, `chunks_total`,
`queries_total`, `queries_answered`, `knowledge_gaps` (not-found count),
`avg_latency_ms`, `feedback_helpful`, `feedback_unhelpful`.

All scoped to the caller's tenant.

## Companion endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/admin/stats` | the metric tiles |
| GET | `/api/admin/queries?limit=` | recent questions (mode, confidence, latency, feedback) |
| GET | `/api/admin/gaps?limit=` | [knowledge gaps](23-knowledge-gaps.md) |
| GET | `/api/admin/readiness` | [rollout readiness](36-enterprise-readiness.md) |

## Interfaces

UI: `/insights` (tiles + gaps panel + readiness panel + recent questions table).

## Permissions

`insights.read` — held by `member`, `tenant_admin`, `service`. (The nav link is
shown to members too.)

## Source

- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — `stats`, `recent_queries`, `knowledge_gaps`
- [`frontend/src/app/(dashboard)/insights/page.tsx`](../../frontend/src/app/(dashboard)/insights/page.tsx)

## Related

[Query history](32-query-history.md) · [Answer feedback](22-answer-feedback.md) ·
[Enterprise readiness view](36-enterprise-readiness.md)
