# Observability

## What it does

Open, pluggable monitoring for the platform: metrics, structured domain events
and request traces. Application code emits signals through one facade; where they
are sent (stdout, SQLite, Prometheus, a webhook, OpenTelemetry, or a client's own
backend) is chosen by configuration, with no vendor as a hard dependency.

## How it works

- **Three signals** — metrics (`count` / `gauge` / `observe`), events
  (`event(kind, **fields)`), spans (`with span(name):`). An always-on in-process
  registry aggregates metrics so `/metrics` and the JSON snapshot work even with
  no sinks.
- **Sinks are plugins** selected by `OBSERVABILITY_SINKS`. Built-in: `noop`,
  `stdout` (JSON lines), `sqlite` (queryable, separate DB), `prometheus`
  (`/metrics`), `webhook` (batched POST), `otlp` (OTLP/HTTP spans). Add your own
  by implementing `Sink` and registering it in `SINK_BUILDERS`.
- **Never breaks a request** — every sink call is guarded; blocking sinks run
  off-thread with a bounded, drop-oldest queue; disabled = no-op.
- **Automatic correlation** — the HTTP middleware assigns `X-Request-ID` and
  binds `route`; `get_principal` binds `tenant` + `actor`; events and spans pick
  these up.
- **Instrumented**: HTTP layer, RAG pipeline stages, ingestion stages,
  connectors, auth, LLM/embedding backends, dependency health (background probe).

## Interfaces

| Method | Path | Permission |
|--------|------|-----------|
| GET | `/metrics` | none (optional `OBS_PROMETHEUS_TOKEN`); needs the `prometheus` sink |
| GET | `/api/observability/config` | `observability.read` |
| GET | `/api/observability/metrics` | `observability.read` |
| GET | `/api/observability/events?kind=&since_seconds=&limit=` | `observability.read` |
| GET | `/api/observability/traces/{request_id}` | `observability.read` |

UI: `/observability` — rate / latency percentiles / errors, RAG stage timings,
answer outcomes, ingest throughput, dependency health, recent events, and a
request-id → trace lookup.

## Permissions

`observability.read` — held by `tenant_admin`, `service`, `superadmin`.
Tenant-scoped principals see only their workspace's slice; superadmin sees all.
It is operational telemetry, not workspace content.

## Configuration

`OBSERVABILITY_ENABLED`, `OBSERVABILITY_SINKS`, `OBSERVABILITY_SERVICE_NAME`,
`OBSERVABILITY_SAMPLE_TRACES`, `OBSERVABILITY_MAX_SERIES`,
`OBSERVABILITY_HEALTH_PROBE_SECONDS`, plus per-sink `OBS_*` vars. Full list and
client scenarios: [`../OBSERVABILITY.md`](../OBSERVABILITY.md).

## Source

- [`backend/app/observability/`](../../backend/app/observability/) — facade, registry, dispatcher, middleware, sinks
- [`backend/app/routers/observability.py`](../../backend/app/routers/observability.py) — read APIs
- [`backend/tests/test_observability.py`](../../backend/tests/test_observability.py)
- [`frontend/src/app/(dashboard)/observability/page.tsx`](../../frontend/src/app/(dashboard)/observability/page.tsx)

## Related

[Audit log](33-audit-log.md) (the compliance record; observability is the ops
stream) · [Health check](37-health-check.md) · [Workspace insights](31-workspace-insights.md) ·
[Roles & permissions](03-roles-and-permissions.md)
