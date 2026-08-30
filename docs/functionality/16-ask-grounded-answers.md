# Ask — grounded answers with citations

## What it does

Answers a natural-language question using only the workspace's documents, with
inline citations, a confidence score, and a logged query id for feedback.

## How it works

1. Retrieve the most relevant chunks for the question, restricted to what the
   caller may see ([Search scope](19-search-scope.md),
   [Retrieval & reranking](20-retrieval-and-reranking.md)).
2. If nothing clears the score threshold → return the **not-found** message and
   log a [knowledge gap](23-knowledge-gaps.md).
3. Otherwise build a grounded prompt (numbered context blocks + system rules for
   language, refusal-outside-knowledge, citation style) and call the tenant's
   [LLM](26-model-connectors.md).
4. If the LLM is unavailable and `LLM_FALLBACK_TO_EXTRACTIVE` is on → return the
   top excerpts instead ([Extractive fallback](24-extractive-fallback.md)).
5. Log the query (question, answer, mode, confidence, latency, sources,
   `user_id`) and return `{query_id, answer, mode, confidence, sources[]}`.

`mode` is one of `llm`, `llm_unavailable`, `not_found`, `model_blocked`.

## Interfaces

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/query/ask` | one-shot answer; body `{question, filters?, scope?}` |

`filters`: `{doc_ids?, source?, filename?}`. `scope`:
`workspace | company | all` (default `all`).

UI: `/ask` (also offers a "Search in" scope selector and starter questions).

## Permissions

`query.run` (member / tenant_admin / service). Superadmin cannot ask.

## Configuration

`ANSWER_LANGUAGE`, `ANSWER_REFUSE_OUTSIDE_KNOWLEDGE`, `ANSWER_INCLUDE_CITATIONS`,
`LLM_FALLBACK_TO_EXTRACTIVE`, plus retrieval/model settings.

## Source

- [`backend/app/routers/query.py`](../../backend/app/routers/query.py) — `ask`
- [`backend/app/services/rag.py`](../../backend/app/services/rag.py) — `answer`, `_build_prompts`

## Related

[Streaming answers](17-streaming-answers.md) · [Citations & grounding](21-citations-and-grounding.md) ·
[Answer feedback](22-answer-feedback.md)
