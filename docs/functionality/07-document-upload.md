# Document upload

## What it does

Adds one or more files to the knowledge base with optional enterprise metadata.
Files are parsed, chunked, embedded and indexed automatically.

## How it works

- `POST /api/documents/upload` accepts a multipart `files[]` list plus form
  fields: `department`, `confidentiality` (`public|internal|confidential`),
  `tags` (comma-separated), and the ownership fields `scope` / `owner_user_id`
  (see [Document scope](09-document-scope.md)).
- Each file is validated (extension in the supported set, size ≤
  `MAX_UPLOAD_MB`), de-duplicated by content hash within its ownership scope, and
  a `Document` row is created with `status=queued`.
- Ingestion runs as a FastAPI background task; the response returns immediately
  with `{accepted[], rejected[]}` where each rejection carries a reason.
- The UI polls the document list every 2.5 s while anything is `queued` /
  `processing`.

## Interfaces

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/documents/upload` | upload files (multipart) |
| GET | `/api/documents?scope=&owner_user_id=&status=&source=` | list visible docs |

UI: `/documents` → **Upload** card. A visibility selector chooses company-wide
vs personal (members are locked to personal).

## Permissions

`document.write.workspace` to reach the endpoint. Publishing company-wide, or
targeting another user's workspace, additionally needs `document.write.tenant`.

## Configuration

`MAX_UPLOAD_MB` (default 50). Supported extensions: see
[File-format support](11-file-format-support.md).

## Source

- [`backend/app/routers/documents.py`](../../backend/app/routers/documents.py)
- [`backend/app/services/ingestion.py`](../../backend/app/services/ingestion.py) — `queue_document`
- [`frontend/src/app/(dashboard)/documents/page.tsx`](../../frontend/src/app/(dashboard)/documents/page.tsx)

## Related

[Bulk ZIP ingestion](08-bulk-zip-ingestion.md) ·
[Ingestion pipeline](10-ingestion-pipeline.md) ·
[Document lifecycle & de-duplication](12-document-lifecycle.md)
