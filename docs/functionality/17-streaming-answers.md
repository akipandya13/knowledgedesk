# Streaming answers (SSE)

## What it does

Streams an answer token-by-token so the UI shows text as it is generated.

## How it works

- `POST /api/query/ask/stream` returns `text/event-stream` with frames of
  `data: {json}\n\n`. (It's a POST, so the browser reads the body stream and
  parses frames by hand rather than using `EventSource`.)
- Event sequence:
  - `meta` — mode, `sources[]`, `confidence`, model info (sent before the first token)
  - `token` — one text delta (repeated)
  - `status` — sent if generation falls back to extractive mid-stream
  - `error` — sent if generation fails and no fallback is configured
  - `done` — carries the `query_id` for feedback
- Retrieval, grounding, scope enforcement, not-found handling and query logging
  are identical to the non-streaming path.

## Interfaces

| Method | Path |
|--------|------|
| POST | `/api/query/ask/stream` |

Body identical to `/api/query/ask`. UI: `/ask` uses this by default
(`streamAsk` in [`frontend/src/lib/api/query.ts`](../../frontend/src/lib/api/query.ts)).

## Permissions

`query.run`.

## Source

- [`backend/app/routers/query.py`](../../backend/app/routers/query.py) — `ask_stream`
- [`backend/app/services/rag.py`](../../backend/app/services/rag.py) — `answer_stream`
- [`backend/app/services/llm.py`](../../backend/app/services/llm.py) — `generate_stream`

## Related

[Ask — grounded answers](16-ask-grounded-answers.md) · [Extractive fallback](24-extractive-fallback.md)
