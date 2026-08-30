# Model profiles

## What it does

Bundles a full set of embedding / reranker / generation / retrieval settings
into one named choice a workspace admin can pick from a dropdown.

## Built-in profiles

| Key | Label | Embedding | Reranker | LLM | Notes |
|-----|-------|-----------|----------|-----|-------|
| `demo_fast` | Demo Fast / Laptop Safe | MiniLM-L6-v2 | off | `gemma3:4b` | **default**; no large downloads |
| `enterprise_balanced` | Enterprise Balanced | BGE-M3 | bge-reranker-large | `gemma3:12b` | production baseline |
| `premium_best` | Premium Best Quality / GPU | Qwen3-Embedding-4B | Qwen3-Reranker-4B | `gemma3:27b` | needs GPU + `ALLOW_HEAVY_LOCAL_MODELS` |
| `multilingual_efficient` | Multilingual Efficient | jina-embeddings-v3 | bge-reranker-v2-m3 | `gemma3:12b` | multilingual |
| `extractive_zero_llm` | Zero LLM Cost / Extractive | MiniLM-L6-v2 | off | none | cited excerpts only |

## How it works

- Selecting a profile applies its defaults; any explicit fields in the same
  settings request override them (`effective_settings` = global defaults +
  profile + tenant overrides, then normalised).
- Each profile carries `demo_safe` / `requires_gpu` flags the UI shows.
- Premium embedding/reranker models are **blocked at runtime** unless
  `ALLOW_HEAVY_LOCAL_MODELS=true`; large Ollama models are downgraded under
  [laptop-safe mode](29-laptop-safe-mode.md).
- The dropdown options come from `GET /api/admin/model-catalog`.

## Interfaces

Applied through [Workspace settings](27-workspace-settings.md). Catalog:
`GET /api/admin/model-catalog`. UI: `/settings`.

## Permissions

Read catalog / change profile: `model_connector.manage` / `settings.write`
(tenant_admin, service).

## Configuration

`MODEL_PROFILE` (global default), `ALLOW_HEAVY_LOCAL_MODELS`,
`ALLOW_LARGE_OLLAMA_MODELS`, `ALLOW_RERANKER_MODELS`, `HF_TOKEN`.

## Source

- [`backend/app/model_catalog.py`](../../backend/app/model_catalog.py) — `MODEL_PROFILES`, `catalog_payload`
- [`backend/app/tenant_settings.py`](../../backend/app/tenant_settings.py) — `effective_settings`, `profile_defaults`

## Related

[Model connectors](26-model-connectors.md) · [Workspace settings](27-workspace-settings.md) ·
[Laptop-safe mode](29-laptop-safe-mode.md)
