# Heavy Model Guard Fix

## Symptom

The logs show the app trying to load this during `/api/query/ask/stream`:

```text
Loading SentenceTransformer model from Qwen/Qwen3-Embedding-4B
Fetching 2 files ... model-00001-of-00002.safetensors
Warning: You are sending unauthenticated requests to the HF Hub
```

This means the tenant's saved Settings selected the `premium_best` embedding model. A question triggers embedding of the query, so SentenceTransformers starts downloading/loading the selected embedding model before retrieval can happen.

## Fix in this build

- Default profile changed to `demo_fast`.
- Default embedding changed to `sentence-transformers/all-MiniLM-L6-v2`.
- Default LLM changed to `gemma3:4b`.
- Default reranker disabled for the laptop demo.
- Added `ALLOW_HEAVY_LOCAL_MODELS=false` guard.
- Added `AUTO_DOWNGRADE_BLOCKED_MODELS=true` so existing tenants saved with Qwen 4B are reset to `demo_fast` on startup unless heavy models are explicitly allowed.
- Settings UI now warns when a selected model/profile is not laptop-safe.
- If a heavy model is still selected while blocked, Q&A returns a clear admin action message instead of silently downloading.

## To use premium models intentionally

```env
MODEL_PROFILE=premium_best
ALLOW_HEAVY_LOCAL_MODELS=true
AUTO_DOWNGRADE_BLOCKED_MODELS=false
HF_TOKEN=<your_huggingface_token>
LLM_MODEL=gemma3:27b
```

Then run on GPU-backed hardware and re-index documents after changing the embedding model.
