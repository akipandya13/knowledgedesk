# Document lifecycle & de-duplication

## What it does

Tracks each document from queued to ready (or failed), prevents duplicate
ingestion, and supports soft deletion that also purges vectors.

## Status model

`queued → processing → ready` on success; `→ failed` (with `error` text) on any
ingestion error; `→ deleted` on removal.

The `Document` row also carries: `pages`, `chunk_count`, `size_bytes`,
`content_hash`, `source` (`upload | zip | gdrive | sharepoint | seed`),
`department`, `confidentiality`, `tags_json`, `embedding_provider`,
`embedding_model`, `version`, `is_active`, `scope`, `owner_user_id`.

## De-duplication

At registration the SHA-256 of the file content is compared against active
documents **in the same ownership scope** (`tenant_id`, `scope`,
`owner_user_id`). A match is rejected with `Duplicate of document #<id>`. This
lets the same file exist once company-wide and once in a user's workspace
without collision.

## Deletion

`DELETE /api/documents/{id}` soft-deletes: it removes the document's points from
every tenant Qdrant collection, sets `is_active=false` and `status=deleted`. The
row is kept for audit/history.

## Reindex

`POST /api/documents/{id}/reindex` is a guarded placeholder (`501`) — v1 uploads
are immutable; re-upload the file to refresh it.

## Interfaces

| Method | Path |
|--------|------|
| GET | `/api/documents` |
| DELETE | `/api/documents/{id}` |
| POST | `/api/documents/{id}/reindex` (501) |

## Permissions

List: `document.read`. Delete: own personal doc, or `document.write.tenant` for
anything in the workspace. Reindex: `document.write.workspace`.

## Source

- [`backend/app/database.py`](../../backend/app/database.py) — `Document`
- [`backend/app/services/ingestion.py`](../../backend/app/services/ingestion.py) — `register_document`
- [`backend/app/routers/documents.py`](../../backend/app/routers/documents.py) — `delete_document`
- [`backend/app/services/vectorstore.py`](../../backend/app/services/vectorstore.py) — `delete_document`

## Related

[Ingestion pipeline](10-ingestion-pipeline.md) · [Document scope](09-document-scope.md)
