# Performance & caching

## What it does

Keeps the hot paths (a RAG query, a document list, an ingest) fast and
observable: a tuned DB connection pool with composite indexes, an in-process
cache for the per-tenant model config, a shared connection-pooled outbound HTTP
client, and explicit response-time targets surfaced as metrics.

## How it works

- **Response-time targets** — `SLO_API_P95_MS` / `SLO_RAG_ANSWER_P95_MS` /
  `SLO_INGEST_DOC_P95_MS` are compared to the live `http.server.duration.seconds`
  / `rag.answer.seconds` / `ingest.document.seconds` histograms.
  `GET /api/observability/slo` returns `{ok, targets:[…p50_ms, p95_ms, met…]}`;
  the background probe also exports `slo.compliant{slo}` / `slo.p95.seconds{slo}`
  gauges for alerting. Shown on `/observability`.
- **Connection pooling** — one `create_engine` pool with `pool_pre_ping` +
  `pool_recycle`; `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` take
  effect when `DATABASE_URL` is a networked DB. Outbound HTTP goes through one
  shared, pooled `httpx` client (`HTTP_POOL_MAX_*`).
- **Database query optimization** — single-column indexes on every `tenant_id` /
  FK / lookup column (model-declared) plus composite indexes for the
  list/paginate shapes created idempotently in `init_db()`. SQLite runs with
  WAL, a bigger `cache_size`, `temp_store=MEMORY`, and `PRAGMA optimize`.
- **Basic caching** — `resolve_model_config(tenant)` is memoized per
  `(tenant, settings_json)` for `TENANT_CONFIG_CACHE_TTL` seconds
  (`app/cache.py`), invalidated on settings/connector changes. `get_settings()`
  is `@lru_cache`; the embedding model and Qdrant client are singletons.
- **Resource management** — DB sessions via `get_db` / try-finally; the shared
  HTTP clients are closed on shutdown; Starlette's threadpool bounds concurrent
  sync work.

## Interfaces

| Method | Path | Permission |
|--------|------|-----------|
| GET | `/api/observability/slo` | `observability.read` |

Plus `slo.*` gauges on `/metrics` and the JSON snapshot.

## Configuration

`DATABASE_URL`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`,
`DB_POOL_RECYCLE`, `DB_POOL_PRE_PING`, `SQLITE_CACHE_MB`,
`TENANT_CONFIG_CACHE_TTL`, `HTTP_POOL_MAX_CONNECTIONS`, `HTTP_POOL_MAX_KEEPALIVE`,
`SLO_API_P95_MS`, `SLO_RAG_ANSWER_P95_MS`, `SLO_INGEST_DOC_P95_MS`. Full
picture: [`docs/PERFORMANCE.md`](../PERFORMANCE.md).

## Source

- [`backend/app/database.py`](../../backend/app/database.py) — engine/pool, PRAGMAs, `_ensure_indexes`
- [`backend/app/cache.py`](../../backend/app/cache.py) · [`backend/app/http_client.py`](../../backend/app/http_client.py)
- [`backend/app/observability/slo.py`](../../backend/app/observability/slo.py)
- [`backend/tests/test_performance.py`](../../backend/tests/test_performance.py)

## Related

[Observability](41-observability.md) · [Health checks](37-health-check.md) ·
[Resilience & recovery](52-resilience-and-recovery.md) ·
[Model connectors](26-model-connectors.md)
