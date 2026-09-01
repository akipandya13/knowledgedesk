# Health checks — liveness, readiness, dependencies

## What it does

Three unauthenticated endpoints, split the way an orchestrator (Kubernetes,
ECS, a load balancer) expects:

| Endpoint | Question | Cost | Codes |
|----------|----------|------|-------|
| `GET /livez` (alias `GET /healthz`) | is the process alive / not wedged? | no I/O, no dependency checks | always `200` |
| `GET /readyz` | can it serve traffic *now*? | probes every required dependency | `200` ready · `503` not ready |
| `GET /api/health` | detailed status for a dashboard / uptime monitor | probes dependencies + samples resources | `200` |

## How it works

- **Liveness** — `{"status":"alive","uptime_seconds":N}`. If this ever fails to
  respond the process is stuck and should be restarted. Registered before the
  SPA catch-all so it returns JSON, not `index.html`.
- **Readiness** — 200 only when **startup bootstrap has completed** *and* every
  **required** dependency is `ok`; otherwise `503` with the same body so a probe
  can log *why*:

  ```json
  {
    "ready": false,
    "bootstrap_complete": true,
    "uptime_seconds": 42.1,
    "dependencies": [
      {"name": "db",     "status": "ok",   "required": true,  "latency_ms": 0.4, "detail": null},
      {"name": "qdrant", "status": "down", "required": true,  "latency_ms": 12.0, "detail": "unreachable"},
      {"name": "llm",    "status": "down", "required": false, "latency_ms": 30.1, "detail": "ollama unreachable"}
    ]
  }
  ```

- **Dependency health** — `db` (`SELECT 1`), `qdrant` (`get_collections()`),
  `llm` (provider readiness). Each is timed; every probe emits
  `dependency.up{dependency}` (gauge) and `dependency.check.seconds{dependency}`
  (histogram). A background loop re-runs the probes every
  `OBSERVABILITY_HEALTH_PROBE_SECONDS` so monitoring sees an outage even when
  the app is idle.
- **`llm` is not required for readiness.** When the LLM backend is down the app
  still serves grounded extractive answers — a degradation, not an outage.
  `db` and `qdrant` are required.
- **`/api/health`** adds `ready`, the `dependencies` list, `resources` (a small
  CPU/memory/FD/thread snapshot — see
  [Observability](41-observability.md#4-what-is-instrumented)), and keeps the
  legacy top-level `qdrant` / `llm` / `llm_provider` / `llm_model` keys.

## Interfaces

| Method | Path | Auth |
|--------|------|------|
| GET | `/livez`, `/healthz` | none |
| GET | `/readyz` | none |
| GET | `/api/health` | none |

`docker-compose.yml` uses `/livez` as the `app` container healthcheck; `web`
waits for `condition: service_healthy`. Behind `TrustedHostMiddleware` /
`FORCE_HTTPS_REDIRECT`, add the probe source host / use HTTPS accordingly.

## Source

- [`backend/app/health.py`](../../backend/app/health.py) — `liveness`, `readiness`, `check_dependencies`, `health_report`
- [`backend/app/main.py`](../../backend/app/main.py) — endpoints + background probe + `mark_ready()`
- [`backend/app/observability/resources.py`](../../backend/app/observability/resources.py) — the `resources` snapshot
- [`backend/tests/test_metrics_health.py`](../../backend/tests/test_metrics_health.py)

## Related

[Observability](41-observability.md) · [Web client architecture](39-web-client-architecture.md)
