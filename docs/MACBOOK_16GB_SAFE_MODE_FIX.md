# MacBook 16 GB Safe Mode Fix

## What was breaking

The previous package correctly downgraded the embedding model from `Qwen/Qwen3-Embedding-4B` to `sentence-transformers/all-MiniLM-L6-v2`, but a stale tenant setting could still keep reranking enabled.

That caused the first Ask request to load:

```text
BAAI/bge-reranker-base
```

A reranker is not as large as Qwen 4B, but it is still a Hugging Face CrossEncoder download/load path and can make the app look stuck on a 16 GB MacBook.

## Root cause

There were two issues:

1. Tenant settings persisted from older dropdown selections.
2. Boolean normalization used `bool(value)`, so a string like `"false"` could become `True` in Python.

## Fix

This build adds:

- Robust boolean parsing for tenant settings.
- `LAPTOP_SAFE_MODE=true` by default.
- `ALLOW_RERANKER_MODELS=false` by default.
- Startup cleanup of stale tenant reranker settings.
- Disabled reranker option in the admin model dropdown.
- Runtime guard so optional rerankers cannot download/load unless explicitly allowed.

## Recommended settings for local demo

```env
MODEL_PROFILE=demo_fast
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
LLM_MODEL=gemma3:4b
RERANKER_ENABLED=false
RERANKER_MODEL=
LAPTOP_SAFE_MODE=true
ALLOW_RERANKER_MODELS=false
ALLOW_HEAVY_LOCAL_MODELS=false
```

## To intentionally enable reranking

Only do this after the base demo is stable:

```env
ALLOW_RERANKER_MODELS=true
RERANKER_ENABLED=true
RERANKER_MODEL=BAAI/bge-reranker-base
```

Restart containers after changing `.env`.
