# Retrieval & reranking pipeline

## What it does

Finds the chunks most likely to answer a question and trims them to fit the
LLM's context budget.

## How it works (`rag.retrieve`)

1. **Embed the query** with the tenant's embedding model.
2. **Vector search** the tenant's Qdrant collection (`kd_<slug>_<provider>_<model>`)
   for `retrieval_top_k` hits above `retrieval_score_threshold`, with the
   [access filter](19-search-scope.md) and any user `filters` (`doc_ids`,
   `source`, `filename`, `department`, `confidentiality`) applied.
3. **Rerank (optional)** — if `reranker_enabled` and a `reranker_model` are set,
   a cross-encoder re-scores the hits and keeps the top `rerank_top_k`. Reranking
   is a best-effort quality layer: if the model is blocked by
   [safe mode](29-laptop-safe-mode.md) or fails to load, vector-search order is
   used instead and Q&A still works.
4. **Context-budget trim** — hits are accumulated until
   `retrieval_max_context_chars` is reached (always keeping at least one).

The collection name embeds the embedding model, so vectors from different models
are never mixed.

## Interfaces

Internal — powers [Ask](16-ask-grounded-answers.md) and
[Semantic search](18-semantic-search.md).

## Configuration

`RETRIEVAL_TOP_K` (12), `RETRIEVAL_SCORE_THRESHOLD` (0.28),
`RETRIEVAL_MAX_CONTEXT_CHARS` (9000), `RERANKER_ENABLED`, `RERANKER_MODEL`,
`RERANK_TOP_K` — all overridable per workspace via a [profile](25-model-profiles.md)
or [settings](27-workspace-settings.md).

## Source

- [`backend/app/services/rag.py`](../../backend/app/services/rag.py) — `retrieve`
- [`backend/app/services/vectorstore.py`](../../backend/app/services/vectorstore.py) — `search`
- [`backend/app/services/reranker.py`](../../backend/app/services/reranker.py)

## Related

[Model profiles](25-model-profiles.md) · [Embedding lock](28-embedding-lock.md)
