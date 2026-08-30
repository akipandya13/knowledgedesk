# Connector sync & run history

## What it does

Configures, tests and runs per-workspace data connectors (Google Drive,
SharePoint), and keeps a history of every sync run for the UI.

## How it works

- **CRUD** — a `DataConnector` row holds `provider`, non-secret `config_json`,
  Fernet-encrypted `secret_encrypted`, `is_active`, and last-sync summary fields.
  Secrets are never returned by the API (only `secret_fields_set` names).
- **Test** — validates config + credentials and lists visible files, returning
  `{ok, detail}` like `"42 files visible, 37 supported types"` without ingesting.
- **Sync** — creates a `ConnectorSyncRun` (`status=running`) and launches a
  background worker: list → download → `register_document` → `ingest_document`,
  tallying `queued / skipped / failed`. Only one run per connector at a time; a
  run older than 30 min is treated as stuck and superseded.
- **Runs** — `GET /{id}/runs` returns recent runs with counts, detail text, and
  start/finish timestamps. The connector row also caches `last_sync_status` /
  `last_sync_detail`.
- All connector documents are **company-wide** (`scope=tenant`).

## Interfaces

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/connectors/providers` | field spec per provider |
| GET/POST | `/api/connectors` | list / create |
| PUT/DELETE | `/api/connectors/{id}` | update / delete |
| POST | `/api/connectors/{id}/test` | dry-run |
| POST | `/api/connectors/{id}/sync` | start a sync |
| GET | `/api/connectors/{id}/runs` | run history |
| GET | `/api/connectors/status` | legacy `.env` global connectors (deprecated) |

UI: `/connectors`.

## Permissions

`data_connector.manage` (tenant_admin / service). Superadmin has no access.

## Configuration

Credentials live in the connector row, not `.env`. `STALE_RUN_MINUTES = 30`.

## Source

- [`backend/app/routers/connectors.py`](../../backend/app/routers/connectors.py)
- [`backend/app/services/connectors/`](../../backend/app/services/connectors/)
- [`backend/app/database.py`](../../backend/app/database.py) — `DataConnector`, `ConnectorSyncRun`

## Related

[Google Drive connector](13-google-drive-connector.md) ·
[SharePoint connector](14-sharepoint-connector.md) ·
[Ingestion pipeline](10-ingestion-pipeline.md)
