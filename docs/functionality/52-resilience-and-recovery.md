# Resilience & recovery

## What it does

Keeps the service up and its state consistent through transient failures,
hung requests, retried clients and hard restarts: timeouts, retries with
backoff, `Idempotency-Key` replay, a startup reconciler, and process-wide error
isolation.

## How it works

- **Graceful error handling** — one global `@app.exception_handler(Exception)`
  turns any bug into a correlated `500` (`{"detail","request_id"}`, no stack
  trace); a request over the ceiling returns `504`; the LLM being down falls
  back to an extractive answer; a failed ingest marks that document `failed`
  without crashing the worker.
- **Timeouts** — `RequestTimeoutMiddleware` bounds every `/api/*` request
  (`REQUEST_TIMEOUT_SECONDS`, default 60; SSE exempt). Every outbound call has an
  explicit timeout; SQLite gets a `busy_timeout`.
- **Retries** — `app/resilience.py` `retry_call` / `aretry_call`: exponential
  backoff + jitter, a per-call-site retryable-exception set. Wired into the
  vector store (`qdrant.search` / `qdrant.upsert`), the network embedding
  providers, and connector `list` / `download`. `retry.attempts{op}` /
  `retry.exhausted{op}` metrics.
- **Idempotency** — send `Idempotency-Key` on a mutating request;
  `IdempotencyMiddleware` replays the stored response on a retry, `409`s a key
  reused with a different body, and stores nothing on a 5xx so a real retry is
  possible. Keyed per principal.
- **Failure recovery** — `recovery.reconcile_on_startup(db)` (once per boot):
  documents stuck in `processing` and connector runs stuck in `running` past
  `RECOVERY_STUCK_MINUTES` are closed out as `failed` with a clear reason;
  expired auth/refresh/idempotency rows are pruned. `recovery.reconciled` event.
- **Error isolation** — per-document ingest, per-file connector download, and
  best-effort observability / audit / activity all contain their own failures;
  tenant isolation bounds a data fault to one workspace.

## Interfaces

No new endpoints. `Idempotency-Key` is an optional request header on
`POST`/`PUT`/`PATCH`/`DELETE` under `/api/`; a replay carries
`Idempotency-Replayed: true`. A timeout returns `504`.

## Configuration

`REQUEST_TIMEOUT_SECONDS`, `REQUEST_TIMEOUT_EXEMPT_PREFIXES`,
`RETRY_MAX_ATTEMPTS`, `RETRY_BASE_DELAY_MS`, `RETRY_MAX_DELAY_MS`,
`IDEMPOTENCY_ENABLED`, `IDEMPOTENCY_TTL_HOURS`, `RECOVERY_STUCK_MINUTES`,
`SQLITE_BUSY_TIMEOUT_MS`. Full picture: [`docs/RESILIENCE.md`](../RESILIENCE.md).

## Source

- [`backend/app/resilience.py`](../../backend/app/resilience.py) · [`timeout_middleware.py`](../../backend/app/timeout_middleware.py) · [`idempotency.py`](../../backend/app/idempotency.py) · [`recovery.py`](../../backend/app/recovery.py)
- [`backend/app/main.py`](../../backend/app/main.py) — middleware wiring + `reconcile_on_startup`
- [`backend/tests/test_resilience.py`](../../backend/tests/test_resilience.py)

## Related

[Health checks](37-health-check.md) · [Backup & restore](53-backup-and-restore.md) ·
[Observability](41-observability.md) · [Multi-tenancy](05-multi-tenancy-and-workspaces.md)
