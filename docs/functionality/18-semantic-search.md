# Semantic search

## What it does

Returns the most relevant document passages for a query — no LLM, instant, zero
cost. Useful for "find the paragraph" rather than "answer the question".

## How it works

- `POST /api/query/search` runs the same retrieval as Ask (embed → vector search
  → optional rerank → context-budget trim) but stops there and returns the
  passages.
- Response: `{results: [{n, filename, page, score, rerank_score?, snippet}]}`.
- Access is scoped exactly like Ask — the caller only sees their own personal
  docs plus company-wide docs, narrowed by `scope`.
- If the embedding model is blocked by safe mode, it returns `409` with an
  admin-facing explanation.

## Interfaces

| Method | Path |
|--------|------|
| POST | `/api/query/search` |

Body `{question, filters?, scope?}` — same shape as Ask.

## Permissions

`query.run`.

## Configuration

Retrieval settings (`RETRIEVAL_TOP_K`, `RETRIEVAL_SCORE_THRESHOLD`,
`RETRIEVAL_MAX_CONTEXT_CHARS`) and reranker settings.

## Source

- [`backend/app/routers/query.py`](../../backend/app/routers/query.py) — `search`
- [`backend/app/services/rag.py`](../../backend/app/services/rag.py) — `retrieve`, `_sources`

## Related

[Retrieval & reranking](20-retrieval-and-reranking.md) · [Search scope](19-search-scope.md)
