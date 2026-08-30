# Health check

## What it does

One unauthenticated endpoint that reports whether the app and its dependencies
are up.

## How it works

`GET /api/health` returns:

```json
{
  "app": "ok",
  "qdrant": "ok" | "down",
  "llm": "ok" | "down" | "disabled",
  "llm_provider": "ollama",
  "llm_model": "gemma3:4b",
  "environment": "demo"
}
```

- `qdrant` — a `get_collections()` probe.
- `llm` — `ollama` tags probe (or provider-specific readiness); `disabled` when
  `LLM_PROVIDER=none`.

Used by `docker compose` healthchecks and uptime monitors.

## Interfaces

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/health` | none |

## Source

- [`backend/app/main.py`](../../backend/app/main.py) — `health`
- [`backend/app/services/vectorstore.py`](../../backend/app/services/vectorstore.py) — `healthy`
- [`backend/app/services/llm.py`](../../backend/app/services/llm.py) — `is_available`

## Related

[Web client architecture](39-web-client-architecture.md)
