# Embedding lock

## What it does

Freezes a workspace's embedding model once it has indexed documents, so stored
vectors stay valid.

## Why

Every vector in Qdrant was produced by a specific embedding model with a specific
dimensionality. Switching models would make existing vectors incomparable to new
query vectors — silently wrong retrieval. The lock makes that a hard error
instead.

## How it works

- `embedding_locked(tenant)` = "has at least one `Document` with `status=ready`".
- While locked, `PUT /api/admin/settings` rejects (`409`) any change to
  `embedding_connector_id`, `embedding_model`, or `embedding_provider`.
- Updating an embedding **model connector** that is the selected one is likewise
  restricted: you may rotate credentials, but not change its `model_id` or
  `dimensions` (`409`).
- On first successful ingest the workspace snapshots
  `settings_json.embedding_locked_to = {provider, model, connector_id}` for
  display/diagnostics.
- `GET /api/admin/config` reports `embedding_locked`, `embedding_locked_reason`,
  `embedding_locked_to`, and an `index_status` block showing whether a reindex
  would be required.

## To change the embedding model

Delete the workspace and recreate it, or re-index from scratch.

## Permissions

Enforced inside `settings.write` / `model_connector.manage` operations.

## Source

- [`backend/app/tenant_settings.py`](../../backend/app/tenant_settings.py) — `embedding_locked`
- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — `update_tenant_settings`, `update_connector`
- [`backend/app/services/ingestion.py`](../../backend/app/services/ingestion.py) — snapshot on first ingest

## Related

[Workspace settings](27-workspace-settings.md) · [Model connectors](26-model-connectors.md) ·
[Ingestion pipeline](10-ingestion-pipeline.md)
