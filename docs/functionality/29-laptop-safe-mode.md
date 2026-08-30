# Laptop-safe mode & heavy-model guard

## What it does

Stops a 16 GB MacBook / demo deployment from silently triggering multi-GB model
downloads or loading GPU-class models during a query.

## How it works

Three layers:

1. **Runtime guard** — `embeddings._guard_model` / `reranker._guard_model` raise
   `ModelLoadBlocked` / `RerankerBlocked` if a `HEAVY_LOCAL_MODELS` entry is
   selected and `ALLOW_HEAVY_LOCAL_MODELS` is not `true`. Q&a returns a
   `model_blocked` answer with admin instructions rather than hanging.
2. **Settings clamp** — `PUT /api/admin/settings` in `LAPTOP_SAFE_MODE`, when a
   workspace has no model connector selected, resets unsafe profiles / non-safe
   Ollama models (`LARGE_OLLAMA_MODELS`) / reranker downloads to `demo_fast` and
   returns a `note`.
3. **Startup sweep** — `_enforce_safe_model_defaults` on boot downgrades stale
   tenant settings left in Docker volumes from earlier builds (heavy HF models,
   large Ollama models, `bool("false")` reranker bug).

Workspaces that select a **model connector** (Bedrock / Azure / hosted / a
configured local endpoint) are exempt — they manage their own backend and are
not at risk of an accidental local download.

## Ollama auto-pull

If `OLLAMA_AUTO_PULL_SAFE_MODELS` is on, a missing model that is in the
laptop-safe allowlist (`gemma3:4b`) is pulled once automatically; anything else
must be pre-pulled or explicitly allowed.

## Configuration

`LAPTOP_SAFE_MODE` (default true), `ALLOW_HEAVY_LOCAL_MODELS`,
`ALLOW_LARGE_OLLAMA_MODELS`, `ALLOW_RERANKER_MODELS`,
`AUTO_DOWNGRADE_BLOCKED_MODELS`, `OLLAMA_AUTO_PULL_SAFE_MODELS`, `HF_TOKEN`.

## Source

- [`backend/app/services/embeddings.py`](../../backend/app/services/embeddings.py) — `_guard_model`
- [`backend/app/services/reranker.py`](../../backend/app/services/reranker.py) — `_guard_model`
- [`backend/app/main.py`](../../backend/app/main.py) — `_enforce_safe_model_defaults`
- [`backend/app/model_catalog.py`](../../backend/app/model_catalog.py) — `HEAVY_LOCAL_MODELS`, `LARGE_OLLAMA_MODELS`

## Related

[Model profiles](25-model-profiles.md) · [Extractive fallback](24-extractive-fallback.md)
