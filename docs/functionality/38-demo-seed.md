# Demo seed

## What it does

Loads the bundled sample company documents into a workspace with one click, so a
fresh demo has something to search.

## How it works

- `POST /api/demo/seed` reads `/app/sample_docs` (mounted read-only from
  `./sample_docs`), skips files already present by filename, and queues the rest
  as **company-wide** documents (`source=seed`, `scope=tenant`).
- Each file ingests through the normal [pipeline](10-ingestion-pipeline.md).
- Returns `{queued: N}`, or a `note` if the sample directory is not mounted.

## Interfaces

| Method | Path |
|--------|------|
| POST | `/api/demo/seed` |

UI: **Load sample documents** button on `/documents` (shown to workspace admins
only).

## Permissions

`document.write.tenant` (tenant_admin, service). Members cannot seed.

## Configuration

`./sample_docs` volume mount in `docker-compose.yml`.

## Source

- [`backend/app/main.py`](../../backend/app/main.py) — `seed_demo`
- [`sample_docs/`](../../sample_docs/)

## Related

[Document upload](07-document-upload.md) · [Ingestion pipeline](10-ingestion-pipeline.md)
