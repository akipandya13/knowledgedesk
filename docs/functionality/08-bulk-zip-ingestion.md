# Bulk ZIP ingestion

## What it does

Ingests a whole folder export in one request — a ZIP from Google Drive,
SharePoint, or a local directory.

## How it works

- `POST /api/documents/upload-zip` takes a single `archive` file plus the same
  metadata + ownership fields as a normal upload.
- The archive is opened in memory; directory entries and `__MACOSX/` noise are
  skipped. Each remaining entry runs through the identical validate → dedup →
  queue path as a single upload.
- The response is `{accepted[], rejected[], total_seen}` so you can see how many
  files were recognised versus skipped (unsupported type, too large, duplicate).
- Every accepted file ingests as its own background task.

## Interfaces

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/documents/upload-zip` | ingest every supported file in a ZIP |

UI: `/documents` → **Upload ZIP archive** button.

## Permissions

Same as [Document upload](07-document-upload.md): `document.write.workspace`,
plus `document.write.tenant` for company-wide or another user's workspace.

## Configuration

`MAX_UPLOAD_MB` applies per file inside the archive.

## Source

- [`backend/app/routers/documents.py`](../../backend/app/routers/documents.py) — `upload_zip`
- [`backend/app/services/ingestion.py`](../../backend/app/services/ingestion.py)

## Related

[Document upload](07-document-upload.md) ·
[Connector sync & run history](15-connector-sync-and-history.md) ·
[File-format support](11-file-format-support.md)
