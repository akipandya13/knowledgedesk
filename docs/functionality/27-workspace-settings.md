# Workspace settings

## What it does

Per-workspace overrides for the RAG and model pipeline, layered on top of the
global defaults.

## Settable keys (`MODEL_SETTING_KEYS`)

`model_profile`, `embedding_provider`, `embedding_model`,
`reranker_enabled`, `reranker_model`, `rerank_top_k`,
`llm_provider`, `llm_model`, `openai_model`,
`llm_connector_id`, `embedding_connector_id`,
`retrieval_top_k`, `retrieval_score_threshold`, `retrieval_max_context_chars`,
`llm_temperature`, `llm_max_tokens`, `answer_language`.

Unknown keys are rejected. Numeric/boolean fields are coerced from form strings.

## How it works

- `PUT /api/admin/settings` merges: if `model_profile` is present its defaults are
  applied first, then the explicit fields in the request, then stored on
  `Tenant.settings_json`.
- **Effective config** at read time = global defaults + selected profile +
  overrides + any selected [model connector](26-model-connectors.md).
- **Safe-mode clamps**: on a laptop-safe deployment, unsafe profiles / large
  Ollama models / reranker downloads are reset to `demo_fast` and the response
  carries a `note` explaining it ([Laptop-safe mode](29-laptop-safe-mode.md)).
- **Embedding lock**: once any document is `ready`, changing the embedding
  model / provider / connector / dimensions returns `409`
  ([Embedding lock](28-embedding-lock.md)).
- `GET /api/admin/config` returns the resolved config plus index status and lock
  state; `GET /api/admin/readiness` is a board-friendly rollout summary.

## Interfaces

| Method | Path |
|--------|------|
| PUT | `/api/admin/settings` |
| GET | `/api/admin/config` |
| GET | `/api/admin/readiness` |

UI: `/settings`.

## Permissions

Write: `settings.write` (tenant_admin, service). Read (`/config`, `/readiness`):
`settings.read` (member and up).

## Configuration

Every key has a global env default (`RETRIEVAL_TOP_K`, `LLM_MODEL`, …); the
workspace override wins.

## Source

- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) — `update_tenant_settings`, `effective_config`
- [`backend/app/tenant_settings.py`](../../backend/app/tenant_settings.py)
- [`backend/app/model_catalog.py`](../../backend/app/model_catalog.py) — `MODEL_SETTING_KEYS`

## Related

[Model profiles](25-model-profiles.md) · [Model connectors](26-model-connectors.md) ·
[Embedding lock](28-embedding-lock.md)
