# KnowledgeDesk v1 — Per-Tenant Model Selection

This build adds tenant-admin model selection from the **Settings** page. Every tenant can choose a different RAG model profile without redeploying the platform.

## Why the default changed

The earlier package exposed `premium_best` with `Qwen/Qwen3-Embedding-4B`. That is a strong retrieval option, but on a normal Docker demo it can trigger multi-GB Hugging Face downloads and CPU loading during the first query.

This package keeps the premium models in the dropdown, but the out-of-box default is now **demo-safe**:

```env
MODEL_PROFILE=demo_fast
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RERANKER_ENABLED=false
LLM_MODEL=gemma3:4b
ALLOW_HEAVY_LOCAL_MODELS=false
AUTO_DOWNGRADE_BLOCKED_MODELS=true
```

If an existing Docker volume already has `premium_best` saved for a tenant, startup will automatically reset that tenant to `demo_fast` unless `ALLOW_HEAVY_LOCAL_MODELS=true` is set. This prevents a query from silently downloading/loading Qwen 4B on CPU.

## Included dropdowns

Tenant admins can configure:

- Model profile: `demo_fast`, `enterprise_balanced`, `premium_best`, `multilingual_efficient`, `extractive_zero_llm`
- Embedding model
- Reranker model and enable/disable switch
- Generation model
- Retrieval pool Top-K
- Final reranked chunks
- Score threshold
- Max context characters
- LLM max tokens
- Temperature

## Profiles

### Demo Fast / Laptop Safe

Best for local Docker demos and CPU machines.

```env
MODEL_PROFILE=demo_fast
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RERANKER_ENABLED=false
LLM_MODEL=gemma3:4b
RETRIEVAL_TOP_K=12
```

### Enterprise Balanced

Recommended production baseline when the host has enough RAM/CPU or GPU support.

```env
MODEL_PROFILE=enterprise_balanced
EMBEDDING_MODEL=BAAI/bge-m3
RERANKER_ENABLED=true
RERANKER_MODEL=BAAI/bge-reranker-large
LLM_MODEL=gemma3:12b
RETRIEVAL_TOP_K=32
RERANK_TOP_K=8
```

### Premium Best / GPU

Highest-quality open-weight profile included in the UI.

```env
MODEL_PROFILE=premium_best
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
RERANKER_ENABLED=true
RERANKER_MODEL=Qwen/Qwen3-Reranker-4B
LLM_MODEL=gemma3:27b
ALLOW_HEAVY_LOCAL_MODELS=true
HF_TOKEN=<your_huggingface_token>
```

Use this only on GPU-backed machines with enough disk/RAM. `HF_TOKEN` is strongly recommended to avoid Hugging Face unauthenticated rate limits.

## Important reindex rule

Changing the embedding model requires documents to be re-indexed. Embeddings from different models are not compatible.

KnowledgeDesk creates model-versioned Qdrant collections:

```text
kd_<tenant_slug>_<embedding_provider>_<embedding_model_slug>
```

Example:

```text
kd_demo_local_sentence_transformers_all_minilm_l6_v2
kd_demo_local_baai_bge_m3
kd_demo_local_qwen_qwen3_embedding_4b
```

This prevents MiniLM, BGE, Jina, and Qwen vectors from being mixed.

## API endpoints

```http
GET /api/admin/model-catalog
GET /api/admin/config
PUT /api/admin/settings
```

Example:

```bash
curl -X PUT http://localhost:8000/api/admin/settings \
  -H 'Authorization: Bearer <tenant-admin-token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "settings": {
      "model_profile": "enterprise_balanced",
      "embedding_model": "BAAI/bge-m3",
      "reranker_enabled": true,
      "reranker_model": "BAAI/bge-reranker-large",
      "llm_model": "gemma3:12b"
    }
  }'
```

## Fix for Qwen 4B logs / slow query

If you see logs like this:

```text
Loading SentenceTransformer model from Qwen/Qwen3-Embedding-4B
Fetching 2 files: 0%| ... model-00001-of-00002.safetensors
```

You have a tenant saved with the premium model. The fixed package prevents this from silently continuing. To use the safe demo profile immediately:

1. Keep `ALLOW_HEAVY_LOCAL_MODELS=false` and `AUTO_DOWNGRADE_BLOCKED_MODELS=true` in `.env`.
2. Restart the app container: `docker compose up -d --build app`.
3. Open **Settings** as the demo admin and confirm profile is **Demo Fast / Laptop Safe**.
4. Re-seed or re-upload documents because the embedding model changed.

To intentionally use Qwen 4B, set `ALLOW_HEAVY_LOCAL_MODELS=true`, set `HF_TOKEN`, run on GPU hardware, rebuild/restart, and then re-index documents.


## MacBook / 16 GB local demo note

For a 16 GB MacBook Pro, keep reranking disabled. Even `BAAI/bge-reranker-base` can trigger a Hugging Face CrossEncoder download/load on the first query. Use rerankers only after setting `ALLOW_RERANKER_MODELS=true` and testing latency.

The laptop-safe defaults are:

```env
MODEL_PROFILE=demo_fast
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
LLM_MODEL=gemma3:4b
RERANKER_ENABLED=false
RERANKER_MODEL=
LAPTOP_SAFE_MODE=true
ALLOW_RERANKER_MODELS=false
```
