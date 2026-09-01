# Application logging

## What it does

Turns every stdlib `logging` call — this app's modules, its dependencies, and
uvicorn's own access/error logs — into one **structured JSON line** carrying
the same correlation ids (`request_id` / `trace_id` / `tenant` / `actor` /
`route`) that [observability](41-observability.md) attaches to events and
spans, plus a global handler that turns any unhandled exception into a safe,
correlated **error log**. WARNING+ records are also mirrored into the
observability event stream so they reach a **centralized** store —
`sqlite` by default, or `postgres` / `mongodb` for a multi-instance deployment.

## How it works

- **Structured, leveled logs.** `app/logging_setup.py` installs one JSON
  formatter on the root logger (`LOG_LEVEL`, default `INFO`; `LOG_FORMAT=text`
  for a human-readable line locally). A `CorrelationFilter` stamps
  `request_id`/`tenant`/`actor`/`route` from the same contextvars the HTTP
  middleware binds, so no call site changes — `logging.getLogger(__name__).info(...)`
  anywhere in the codebase already comes out correlated.
- **uvicorn's access/error logs** are routed through the same pipeline
  (its default handlers are stripped in favour of propagating to root), so
  they're JSON too, not a separately-formatted line.
- **Error logs.** A global `@app.exception_handler(Exception)` logs the
  exception (level `ERROR`, full traceback, `request_id`/`actor` re-bound from
  the request — the handler runs in Starlette's outermost middleware, after
  the per-request context has already been cleared), counts it
  (`app.errors{type}`), emits an `app.error` event, and returns
  `{"detail": "Internal server error", "request_id": ...}` — never the raw
  exception message or a stack trace to the caller.
- **Centralized collection without a second pipeline.** WARNING+ log records
  are mirrored into `app.observability` as an `app.log` event
  (`ObservabilityBridgeHandler`), so they flow to every configured sink —
  including `postgres` / `mongodb` (below) — the same way domain events do.
  The observability subsystem's own loggers are excluded so this can't loop
  back on itself.
- **Access logs and security logs already exist** as their own first-class
  signals and are not duplicated here: see
  [security event logging](49-security-event-logging.md) (`audit_log` +
  authn/authz events) and [user activity tracking](50-user-activity-tracking.md)
  (`activity_log`, the request firehose). This page is specifically about
  *process log records* — `logging.info/warning/error/exception(...)`.

## Centralized log collection — SQL or NoSQL, config-selected

Add `postgres` and/or `mongodb` to `OBSERVABILITY_SINKS` to have every event
(including the `app.log` / `app.error` bridge above) written to a durable,
queryable, cross-instance store instead of (or alongside) the single-node
`sqlite` sink:

| Sink | Backend | Table / collection | Selected by |
|------|---------|---------------------|-------------|
| `postgres` | any Postgres | `OBS_POSTGRES_TABLE` (default `kd_logs`) | `OBS_POSTGRES_DSN` |
| `mongodb` | any MongoDB | `OBS_MONGO_DB.OBS_MONGO_COLLECTION` (default `logs`) | `OBS_MONGO_URI` |

Both are ordinary `Sink` implementations (see `sinks/__init__.py`) — the
`docker-compose.yml` `postgres` / `mongodb` services are **opt-in**
(`docker compose --profile postgres up -d`) for a deployment that doesn't
already run one; point the DSN/URI at any other instance (a customer's RDS,
Atlas, self-hosted cluster, …) and skip the bundled service entirely. Neither
driver (`psycopg`, `pymongo`) is imported unless its sink is actually selected.
A different backend (Elasticsearch, Loki, Splunk HEC, …) is the same one-file
extension used for every other sink.

## Interfaces

No new read API — logs land on stdout (structured) and, via the bridge, on
whatever `GET /api/observability/events?kind=app.log` / `app.error` — or the
`postgres`/`mongodb` store directly — already exposes. See
[Observability](41-observability.md#5-read-apis).

## Configuration

| Env var | Default | Meaning |
|---------|---------|---------|
| `LOG_LEVEL` | `INFO` | root logger level |
| `LOG_FORMAT` | `json` | `json` (structured) or `text` (readable, local dev) |
| `LOG_BRIDGE_LEVEL` | `WARNING` | minimum level mirrored into the observability event stream |
| `OBS_POSTGRES_DSN` / `OBS_POSTGRES_TABLE` / `OBS_POSTGRES_BATCH` | — / `kd_logs` / `50` | `postgres` sink |
| `OBS_MONGO_URI` / `OBS_MONGO_DB` / `OBS_MONGO_COLLECTION` / `OBS_MONGO_BATCH` | — / `knowledgedesk` / `logs` / `50` | `mongodb` sink |

Full picture: [`docs/LOGGING.md`](../LOGGING.md).

## Source

- [`backend/app/logging_setup.py`](../../backend/app/logging_setup.py) — formatter, correlation filter, bridge, `configure_logging`
- [`backend/app/main.py`](../../backend/app/main.py) — wiring + the global exception handler
- [`backend/app/observability/middleware.py`](../../backend/app/observability/middleware.py) — `X-Request-ID` / scope stash
- [`backend/app/observability/sinks/postgres.py`](../../backend/app/observability/sinks/postgres.py), [`mongodb.py`](../../backend/app/observability/sinks/mongodb.py)
- [`backend/tests/test_logging.py`](../../backend/tests/test_logging.py)

## Related

[Observability](41-observability.md) · [Security event logging](49-security-event-logging.md) ·
[User activity tracking](50-user-activity-tracking.md) · [Audit log](33-audit-log.md)
