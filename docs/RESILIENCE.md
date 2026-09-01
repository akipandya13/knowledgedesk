# Resilience & recovery

How KnowledgeDesk stays up and consistent when a dependency blips, a request
hangs, a client retries, or the process is killed mid-work.

| Concern | Mechanism |
|---------|-----------|
| Graceful error handling | global `@app.exception_handler(Exception)` → safe correlated `500`; `504` on timeout; LLM down → extractive answer; ingestion failure → document marked `failed` (worker never crashes); observability / audit / activity writes are best-effort and never raise into the request path |
| Timeouts | per-request ceiling (`RequestTimeoutMiddleware`); explicit `httpx` timeouts on every remote call; `QdrantClient(timeout=30)`; `LLM_TIMEOUT_SECONDS`; SQLite `busy_timeout` |
| Retries | `app/resilience.py` — exponential backoff + jitter around the vector store, remote embedding calls and connector list/download |
| Idempotency | `Idempotency-Key` header → `IdempotencyMiddleware` replays the stored response instead of acting twice |
| Health checks | `/livez`, `/readyz`, `/api/health` — see [functionality/37](functionality/37-health-check.md) |
| Failure recovery | `app/recovery.py` startup reconciler closes out interrupted work |
| Backup / restore | `scripts/backup.py` + `scripts/restore.py` — see [BACKUP_RESTORE.md](BACKUP_RESTORE.md) |
| Error isolation | per-document ingestion, per-file connector download, best-effort subsystems, one process-wide exception boundary |

## Timeouts

`RequestTimeoutMiddleware` wraps every `/api/*` request in
`asyncio.wait_for(REQUEST_TIMEOUT_SECONDS)` (default 60, `0` disables). On
expiry the caller gets `504 {"detail":"Request timed out","request_id":…}` and
`http.server.timeouts{route}` / `http.request.timeout` fire. SSE endpoints are
exempt by prefix (`REQUEST_TIMEOUT_EXEMPT_PREFIXES`). A sync handler already in
the threadpool keeps running to completion — the client just stops waiting.

Every outbound call is individually bounded: `httpx` clients pass an explicit
`timeout=`, the Qdrant client is `timeout=30`, LLM generation uses
`LLM_TIMEOUT_SECONDS`, the one-time Ollama model pull is capped at 15 min (was
unbounded), and SQLite waits `SQLITE_BUSY_TIMEOUT_MS` for a write lock before
raising "database is locked".

## Retries

```python
from app.resilience import retry_call, aretry_call

hits = retry_call(lambda: client().query_points(...),
                  op="qdrant.search", retry_on=(ResponseHandlingException, ConnectionError))
```

`RETRY_MAX_ATTEMPTS` (3) with `RETRY_BASE_DELAY_MS`..`RETRY_MAX_DELAY_MS` full
jitter. The retryable exception set is **passed per call site** so a
deterministic 4xx / auth / validation error fails immediately. Wired into:
`vectorstore.search` / `upsert_chunks` (Qdrant), `embeddings.embed_texts` for
the network providers only (a local model failure is deterministic), and the
connector `list_files` / `download_file` in a sync run. Every retried attempt
increments `retry.attempts{op}`; a give-up increments `retry.exhausted{op}` and
raises `RetryError` (`__cause__` = the last error).

## Idempotency

Send a stable `Idempotency-Key` header on a `POST`/`PUT`/`PATCH`/`DELETE` and a
retry is safe:

| Situation | Result |
|-----------|--------|
| first request | runs; response stored (encrypted), keyed per principal |
| retry, same method + path + body | the stored status + body is replayed, `Idempotency-Replayed: true` |
| same key, **different body** | `409` — a key identifies one request |
| retry while the original is still running | `409` |
| original raised / returned 5xx / body > 256 KB | nothing stored — the client may retry for real |

Identity comes from the bearer JWT claims (no DB) or one API-key lookup, so keys
can't collide across workspaces. Rows older than `IDEMPOTENCY_TTL_HOURS` are
pruned by the startup reconciler.

## Failure recovery

`recovery.reconcile_on_startup(db)` runs once per boot (idempotent,
never blocks startup):

- documents stuck in `processing` older than `RECOVERY_STUCK_MINUTES` → `failed`
  with `error = "Interrupted by a service restart"` (the bytes aren't stored, so
  re-upload is the fix);
- connector sync runs stuck in `running` → `failed`;
- expired / used `auth_tokens`, expired / revoked `refresh_tokens`, and expired
  `idempotency_keys` are pruned.

Counts go to `recovery.reconciled` (event) and `recovery.rows{kind}` (counter).

## Error isolation

- One process-wide exception boundary (`main.py`) — a bug in any handler becomes
  a correlated `500`, not a crashed worker or a leaked stack trace.
- Background work is isolated per unit: `ingest_document` catches every failure
  and marks that one document `failed`; `_run_sync` catches per-file download
  failures and tallies them without aborting the run.
- Cross-cutting subsystems (observability, audit, activity, secret resolution,
  the log→event bridge) are best-effort — every entry point swallows and logs,
  so a sink outage or a bad audit write can't 500 a user action.
- Tenant isolation (see [TENANCY.md](TENANCY.md)) bounds the blast radius of a
  data-level failure to one workspace.

## Source

- [`backend/app/resilience.py`](../backend/app/resilience.py) · [`backend/app/timeout_middleware.py`](../backend/app/timeout_middleware.py) · [`backend/app/idempotency.py`](../backend/app/idempotency.py) · [`backend/app/recovery.py`](../backend/app/recovery.py)
- [`backend/app/database.py`](../backend/app/database.py) — SQLite pragmas, `IdempotencyKey`
- [`backend/scripts/backup.py`](../backend/scripts/backup.py) · [`backend/scripts/restore.py`](../backend/scripts/restore.py)
- [`backend/tests/test_resilience.py`](../backend/tests/test_resilience.py)
