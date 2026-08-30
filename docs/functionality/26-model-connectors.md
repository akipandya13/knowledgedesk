# Model connectors (LLM & embedding backends)

## What it does

Lets a workspace point generation and/or embedding at its own managed backend —
AWS Bedrock, Azure AI Foundry, a local Ollama server, or any OpenAI-compatible
endpoint — instead of the built-in local models.

## Providers

| Provider | Kinds | Key config / secrets |
|----------|-------|----------------------|
| `bedrock` | llm, embedding | `region`; AWS keys optional (falls back to host credential chain) |
| `azure_foundry` | llm, embedding | `endpoint`, `deployment`, `api_version`; `api_key` |
| `ollama` | llm, embedding | `base_url`, `size_class` |
| `openai_compatible` | llm, embedding | `base_url` (`/v1`); `api_key` optional |
| `none` | llm | disables generation → extractive answers |

## How it works

- A `ModelConnector` row holds `kind` (`llm`/`embedding`), `provider`,
  `model_id`, non-secret `config_json`, and Fernet-encrypted `secret_encrypted`.
  The API only ever returns `secret_fields_set` (names), never values.
- A workspace **selects** a connector by id in its settings
  (`llm_connector_id` / `embedding_connector_id`). `resolve_model_config()` then
  layers the connector's runtime keys over the effective settings — a drop-in
  replacement everywhere the pipeline reads model config.
- **Test** (`POST /model-connectors/{id}/test`) does a live round-trip: an LLM
  connector asks the model to reply "OK"; an embedding connector embeds a probe
  string and reports the vector dimension.
- Guard rails: you cannot delete a connector that is currently selected; you
  cannot change an embedding connector's model/dimensions once the workspace has
  indexed documents ([Embedding lock](28-embedding-lock.md)).

## Interfaces

| Method | Path |
|--------|------|
| GET | `/api/admin/model-catalog` |
| GET/POST | `/api/admin/model-connectors` |
| PUT/DELETE | `/api/admin/model-connectors/{id}` |
| POST | `/api/admin/model-connectors/{id}/test` |

UI: `/model-connectors`, selected on `/settings`.

## Permissions

`model_connector.manage` (tenant_admin, service). Superadmin has no access.

## Configuration

Credentials live in the connector row (encrypted with `KD_SECRET_KEY`).

## Source

- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — connector CRUD + test
- [`backend/app/tenant_settings.py`](../../backend/app/tenant_settings.py) — `_connector_overrides`, `resolve_model_config`
- [`backend/app/services/llm.py`](../../backend/app/services/llm.py), [`embeddings.py`](../../backend/app/services/embeddings.py)
- [`backend/app/model_catalog.py`](../../backend/app/model_catalog.py) — `CONNECTOR_PROVIDERS`

## Related

[Model profiles](25-model-profiles.md) · [Credential encryption](30-credential-encryption.md) ·
[Embedding lock](28-embedding-lock.md)
