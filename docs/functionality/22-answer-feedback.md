# Answer feedback

## What it does

Lets a user mark an answer helpful or not helpful. Feedback rolls up into
workspace insights.

## How it works

- Each answer response carries a `query_id`. `POST /api/query/feedback` with
  `{query_id, helpful}` sets `QueryLog.feedback` to `1` (helpful) or `-1` (not).
- The row must belong to the caller's tenant, else `404`.
- Feedback can be changed by calling again; the UI disables the buttons after the
  first vote per answer.
- Counts appear on `/insights` as **👍 Helpful** / **👎 Not helpful** and per-row
  on `/history`.

## Interfaces

| Method | Path |
|--------|------|
| POST | `/api/query/feedback` |

UI: thumbs buttons under each answer on `/ask`.

## Permissions

`feedback.write` (member / tenant_admin / service).

## Source

- [`backend/app/routers/query.py`](../../backend/app/routers/query.py) — `feedback`
- [`backend/app/database.py`](../../backend/app/database.py) — `QueryLog.feedback`

## Related

[Ask — grounded answers](16-ask-grounded-answers.md) · [Workspace insights](31-workspace-insights.md)
