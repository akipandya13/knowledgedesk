# Search scope

## What it does

Lets a user choose which layer of documents a question searches, without ever
being able to reach another user's private documents.

| `scope` | Searches |
|---------|----------|
| `all` (default) | the caller's personal docs **+** company-wide docs |
| `workspace` | only the caller's personal docs |
| `company` | only company-wide docs |

## How it works

- `/api/query/{ask,ask/stream,search}` accept a `scope` field.
- The router builds an **access descriptor** `{user_id, scope}` from the verified
  principal and passes it to retrieval. `user_id` comes from the token, not the
  request.
- `vectorstore._access_condition()` turns it into a Qdrant filter that is
  **AND-ed** with any user filters:
  - `company` → `scope == "tenant"` (or legacy points with no `scope` payload)
  - `workspace` → `owner_user_id == <caller>`
  - `all` → either of the above
- Because the filter is derived server-side, `scope` can only **narrow** the
  visible set — a request can never widen it. A `service` (API-key) caller has no
  `user_id`, so `workspace` falls back to company-wide.
- `QueryLog.user_id` records who asked, enabling per-user history later.

## Interfaces

Field on the Ask/Search request bodies. UI: the "Search in" selector on `/ask`
and the scope tabs on `/documents`.

## Permissions

`query.run`. Scope does not change the permission — it changes the filter.

## Source

- [`backend/app/routers/query.py`](../../backend/app/routers/query.py) — `_access`
- [`backend/app/services/vectorstore.py`](../../backend/app/services/vectorstore.py) — `_access_condition`, `_query_filter`
- [`backend/tests/test_document_scope.py`](../../backend/tests/test_document_scope.py)

## Related

[Document scope](09-document-scope.md) · [Ask — grounded answers](16-ask-grounded-answers.md)
