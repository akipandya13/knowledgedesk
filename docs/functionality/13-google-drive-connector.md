# Google Drive connector

## What it does

Mass-ingests a Google Drive folder (recursively) into a workspace, on demand,
through the normal ingestion pipeline.

## How it works

- **Auth**: a Google Cloud **service account** key (JSON), stored
  Fernet-encrypted. The target folder must be shared with the service-account
  email, or domain-wide delegation is configured and an `impersonate_email` is
  supplied. Access tokens are minted and refreshed with `google-auth`, so a
  connector keeps working indefinitely.
- **List**: recursively walks `folder_id`, following sub-folders, collecting file
  metadata (`id`, `name`, `mimeType`, `size`).
- **Download**: native Google Docs/Sheets/Slides are exported to
  `.docx` / `.xlsx` / `.pptx`; other files download as-is.
- Downloaded bytes go straight into `register_document` + `ingest_document` as
  **company-wide** documents with `source=gdrive`, sharing the same validation
  and de-duplication as manual uploads.

## Configuration fields (per connector)

| Field | Required | |
|-------|----------|--|
| `folder_id` | yes | the long id from the folder URL |
| `impersonate_email` | no | for domain-wide delegation |
| `service_account_json` (secret) | yes | the JSON key, pasted |

Legacy `.env` globals `GDRIVE_ACCESS_TOKEN` / `GDRIVE_FOLDER_ID` are still
recognised by the deprecated status endpoint.

## Interfaces

Managed via the generic data-connector API — see
[Connector sync & run history](15-connector-sync-and-history.md). UI:
`/connectors`.

## Permissions

`data_connector.manage` (tenant_admin / service).

## Source

- [`backend/app/services/connectors/gdrive.py`](../../backend/app/services/connectors/gdrive.py)
- [`backend/app/model_catalog.py`](../../backend/app/model_catalog.py) — `DATA_CONNECTOR_PROVIDERS["gdrive"]`

## Related

[SharePoint connector](14-sharepoint-connector.md) ·
[Connector sync & run history](15-connector-sync-and-history.md) ·
[Credential encryption](30-credential-encryption.md)
