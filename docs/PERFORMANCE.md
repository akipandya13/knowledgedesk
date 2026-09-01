# Performance

## Response-time targets

Demo defaults — tune per deployment (`SLO_*_P95_MS`). They are compared against
the live latency histograms already collected by the app.

| SLO | Metric | p95 budget (default) |
|-----|--------|----------------------|
| `api` | `http.server.duration.seconds` (excluding the RAG ask/search routes) | `SLO_API_P95_MS` = 500 ms |
| `rag_answer` | `rag.answer.seconds` | `SLO_RAG_ANSWER_P95_MS` = 15 s |
| `ingest_document` | `ingest.document.seconds` | `SLO_INGEST_DOC_P95_MS` = 60 s |

- **Read them**: `GET /api/observability/slo` (`observability.read`) →
  `{ok, targets:[{name, target_p95_ms, p50_ms, p95_ms, samples, met}]}`. Also on
  the `/observability` page ("Response-time targets" card).
- **Alert on them**: the background probe refreshes `slo.target.seconds{slo}`,
  `slo.p95.seconds{slo}` and `slo.compliant{slo}` (1/0) gauges every
  `OBSERVABILITY_HEALTH_PROBE_SECONDS`, so Prometheus can alert on
  `slo_compliant == 0`.
- The building blocks (request rate, error rate, latency percentiles,
  throughput, resource utilization) are documented in
  [OBSERVABILITY.md](OBSERVABILITY.md#4-what-is-instrumented).

## Database

- **Connection pool** — one tuned `create_engine` pool: `pool_pre_ping`
  (validate before use) + `pool_recycle` (`DB_POOL_RECYCLE`, 30 min) guard
  against connections dropped by a server/proxy; `DB_POOL_SIZE` /
  `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` apply when `DATABASE_URL` points at a
  networked DB. SQLite (the default) pools cheaply and shares connections across
  reader threads under WAL.
- **`DATABASE_URL`** — blank → SQLite at `{DATA_DIR}/knowledgedesk.db`. Point it
  at `postgresql://…` and the same pool config applies; the SQLite-only PRAGMAs
  and index bootstrap are skipped for other backends.
- **SQLite PRAGMAs** (per connection): `journal_mode=WAL`,
  `synchronous=NORMAL`, `busy_timeout` (`SQLITE_BUSY_TIMEOUT_MS`),
  `cache_size=-{SQLITE_CACHE_MB}*1024`, `temp_store=MEMORY`; `PRAGMA optimize`
  after `init_db()`.
- **Query optimization** — the models carry a single-column index on every
  `tenant_id` / FK / lookup column; `init_db()` also creates composite indexes
  matching the list/paginate shapes (`CREATE INDEX IF NOT EXISTS`, idempotent):

  | index | table | columns |
  |-------|-------|---------|
  | `ix_documents_tenant_active_status` | documents | tenant_id, is_active, status |
  | `ix_documents_tenant_scope_owner` | documents | tenant_id, scope, owner_user_id |
  | `ix_query_log_tenant_created` | query_log | tenant_id, created_at |
  | `ix_query_log_tenant_mode` | query_log | tenant_id, mode |
  | `ix_audit_log_tenant_id_desc` / `_tenant_action` / `_target` | audit_log | tenant_id,id · tenant_id,action · target_type,target_id |
  | `ix_activity_log_tenant_id_desc` / `_tenant_user_id` / `_tenant_category` | activity_log | … |
  | `ix_refresh_tokens_user_revoked` | refresh_tokens | user_id, revoked |
  | `ix_connector_sync_runs_connector` | connector_sync_runs | connector_id, started_at |

## Caching

- **Tenant model config** — `resolve_model_config(tenant)` runs on every query
  and ingest and, with a model connector selected, opens a session and may
  resolve a `${secret:…}` over the network. It is cached in-process
  (`app/cache.py` `TTLCache`) keyed by `(tenant.id, hash(settings_json))` for
  `TENANT_CONFIG_CACHE_TTL` seconds (30; `0` disables). A settings edit yields a
  fresh key automatically; connector CRUD calls `invalidate_tenant_config()`
  for immediacy. Multi-process = each worker warms its own copy; the TTL bounds
  staleness.
- **Settings** — `get_settings()` is `@lru_cache`. Model catalog / profiles are
  static module data.
- `TTLCache` is available for any other hot-path memoization — bounded,
  thread-safe, per-process. It is **not** a shared/distributed cache.

## Resource management

- **Outbound HTTP** — one shared, connection-pooled `httpx.Client` +
  `AsyncClient` (`app/http_client.py`, `HTTP_POOL_MAX_CONNECTIONS` /
  `HTTP_POOL_MAX_KEEPALIVE`) reused by LLM generation and remote embedding
  calls instead of a fresh client (new TCP + TLS) per request. Timeouts stay
  per-call. Closed on shutdown.
- **DB sessions** — always via the `get_db` dependency (try/finally) or an
  explicit `SessionLocal()` with `finally: db.close()`.
- **Qdrant client** — a module singleton with `timeout=30`. **Embedding model** —
  loaded once and cached. **Thread pool** — Starlette's default anyio limiter
  bounds concurrent sync handlers.

## Source

- [`backend/app/database.py`](../backend/app/database.py) — engine/pool, PRAGMAs, `_ensure_indexes`
- [`backend/app/cache.py`](../backend/app/cache.py) · [`backend/app/http_client.py`](../backend/app/http_client.py)
- [`backend/app/observability/slo.py`](../backend/app/observability/slo.py) · [`backend/app/routers/observability.py`](../backend/app/routers/observability.py)
- [`backend/tests/test_performance.py`](../backend/tests/test_performance.py)
