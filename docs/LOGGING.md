# Logging

KnowledgeDesk has three log-shaped streams, on purpose. This is the map;
per-capability detail is in
[functionality/51-application-logging.md](functionality/51-application-logging.md)
and [functionality/49-security-event-logging.md](functionality/49-security-event-logging.md).

| Stream | What | Where it's defined | P0 items it covers |
|--------|------|--------------------|--------------------|
| **Application / error logs** | every stdlib `logging` record — this app, dependencies, uvicorn — as structured JSON; uncaught exceptions via a global handler | `app/logging_setup.py`, `app/main.py` | application logs · error logs · structured logging · log levels · correlation ids · request ids |
| **Security logs** | tamper-evident `audit_log` + authn/authz observability events | `app/services/audit.py`, `docs/GOVERNANCE.md` | security logs · access logs (admin plane) |
| **Access / activity logs** | `http.request` events + the `activity_log` request firehose | `app/observability/middleware.py`, `app/services/activity.py` | access logs |
| **Centralized collection** | any of the above shipped to a durable store | `OBSERVABILITY_SINKS` (`stdout`/`sqlite`/`webhook`/`otlp`/**`postgres`**/**`mongodb`**) | centralized log collection |

## Structured logging & correlation

`configure_logging()` (called at import and again from the FastAPI startup
event — uvicorn installs its own handlers in between) puts **one JSON formatter**
on the root logger:

```json
{"ts":1788278273.358,"level":"INFO","logger":"knowledgedesk.rag","message":"...",
 "module":"rag","line":142,"service":"knowledgedesk","environment":"demo",
 "request_id":"a1b2c3d4","trace_id":"a1b2c3d4","tenant":"acme","actor":"alice@acme.test","route":"/api/query/ask"}
```

- `LOG_LEVEL` (default `INFO`) sets the root level; `LOG_FORMAT=text` swaps to a
  readable line for local `docker compose logs` reading.
- A `CorrelationFilter` reads the same contextvars the HTTP middleware binds
  (`app/observability/context.py`), so **no call site changes** — every existing
  `logging.getLogger(__name__).info(...)` is correlated.
- uvicorn's `uvicorn.access` / `uvicorn.error` loggers are stripped of their own
  handlers and propagate to root → access logs are structured JSON too.
- `request_id` == `trace_id`; the same value is the `X-Request-ID` response
  header and the key for `GET /api/observability/traces/{request_id}`.

## Error logs

One global `@app.exception_handler(Exception)`:

1. logs the exception at `ERROR` with the full traceback and the request's
   `request_id` / `actor` (re-bound from the ASGI scope — the handler runs in
   Starlette's outermost middleware, after the per-request context was cleared),
2. increments `app.errors{type}` and emits an `app.error` event,
3. returns `{"detail":"Internal server error","request_id":"…"}` — **never** the
   exception text or a stack trace to the caller.

Top-level crashes are not tenant-scoped (they escape the request's own
middleware stack); they're visible in the platform-wide observability view.

## Centralized log collection

WARNING+ log records are mirrored into the observability event stream as an
`app.log` event (`LOG_BRIDGE_LEVEL`), so **one shipping config collects
everything** — application logs, error logs, security events, activity. Options:

- **stdout (default)** — JSON lines; collect with Docker's log driver +
  Loki/Fluent Bit/CloudWatch/ELK. Zero extra services.
- **`sqlite`** — local, queryable via `/api/observability/events`; single node.
- **`postgres`** — batched INSERT into `OBS_POSTGRES_TABLE` (default `kd_logs`),
  auto-created. Durable, queryable, cross-instance. Set
  `OBSERVABILITY_SINKS=…,postgres` + `OBS_POSTGRES_DSN`.
- **`mongodb`** — batched `insert_many` into `OBS_MONGO_DB.OBS_MONGO_COLLECTION`
  (default `logs`). Set `OBSERVABILITY_SINKS=…,mongodb` + `OBS_MONGO_URI`.

```bash
# opt-in bundled backends (off by default)
docker compose --profile postgres up -d
#   then in .env:  OBSERVABILITY_SINKS=stdout,sqlite,prometheus,postgres
#                  OBS_POSTGRES_DSN=postgresql://kd:kd@postgres:5432/knowledgedesk

docker compose --profile mongodb up -d
#   then in .env:  OBSERVABILITY_SINKS=stdout,sqlite,prometheus,mongodb
#                  OBS_MONGO_URI=mongodb://kd:kd@mongodb:27017
```

**Config-selected, not hardcoded.** Point `OBS_POSTGRES_DSN` / `OBS_MONGO_URI`
at a customer's own RDS / Atlas / self-hosted instance and skip the bundled
service. A different backend (Elasticsearch, Loki, Splunk HEC, …) is one file:

```python
# app/observability/sinks/mine.py
from .base import Sink
class MySink(Sink):
    name = "mine"; blocking = True
    def on_event(self, e): ...
# app/observability/sinks/__init__.py
SINK_BUILDERS["mine"] = lambda s: MySink(url=s.obs_mine_url)
```

`psycopg` / `pymongo` are imported lazily — the base install carries them but
nothing loads a driver unless its sink is actually named in
`OBSERVABILITY_SINKS`.

## Source

- [`backend/app/logging_setup.py`](../backend/app/logging_setup.py)
- [`backend/app/main.py`](../backend/app/main.py) — `configure_logging`, `unhandled_exception_handler`
- [`backend/app/observability/sinks/postgres.py`](../backend/app/observability/sinks/postgres.py) · [`mongodb.py`](../backend/app/observability/sinks/mongodb.py)
- [`backend/tests/test_logging.py`](../backend/tests/test_logging.py)
- [`docs/OBSERVABILITY.md`](OBSERVABILITY.md) · [`docs/GOVERNANCE.md`](GOVERNANCE.md)
