# SharePoint / OneDrive connector

## What it does

Mass-ingests a SharePoint site's document library (or a specific drive) into a
workspace via Microsoft Graph.

## How it works

- **Auth**: an Azure AD app registration (client credentials flow) with the
  `Sites.Read.All` **application** permission, admin-consented. The client secret
  is stored Fernet-encrypted.
- **List**: enumerates items in the site's default drive (or the configured
  `drive_id`) through the Graph API.
- **Download**: fetches each file's content and hands it to the shared ingestion
  pipeline as a **company-wide** document with `source=sharepoint`.

## Configuration fields (per connector)

| Field | Required | |
|-------|----------|--|
| `tenant_id` | yes | Directory (tenant) ID |
| `client_id` | yes | Application (client) ID |
| `site_id` | yes | `contoso.sharepoint.com,<guid>,<guid>` |
| `drive_id` | no | defaults to the site's document library |
| `client_secret` (secret) | yes | app registration secret |

Legacy `.env` globals `MSGRAPH_*` are recognised by the deprecated status
endpoint.

## Interfaces

Managed via the generic data-connector API — see
[Connector sync & run history](15-connector-sync-and-history.md). UI:
`/connectors`.

## Permissions

`data_connector.manage` (tenant_admin / service).

## Source

- [`backend/app/services/connectors/sharepoint.py`](../../backend/app/services/connectors/sharepoint.py)
- [`backend/app/model_catalog.py`](../../backend/app/model_catalog.py) — `DATA_CONNECTOR_PROVIDERS["sharepoint"]`

## Related

[Google Drive connector](13-google-drive-connector.md) ·
[Connector sync & run history](15-connector-sync-and-history.md) ·
[Credential encryption](30-credential-encryption.md)
