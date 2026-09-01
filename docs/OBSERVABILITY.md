# Observability

An **open, pluggable** monitoring layer. Application code emits signals through
one small facade; *where those signals go* is chosen entirely by configuration.
No vendor is a hard dependency. It is useful with zero external tooling and
scales up to OpenTelemetry / Prometheus / a client's own collector by flipping a
config value.

---

## 1. Model — three signals, one facade, many sinks

```
        application code
   obs.count() obs.gauge() obs.observe() obs.event() obs.span()
                     │
              ┌──────▼───────┐   always on, in-process, bounded
              │   registry   │──▶ counters · gauges · histograms
              └──────┬───────┘        │            │
                     │                ▼            ▼
              ┌──────▼───────┐   GET /metrics   GET /api/observability/metrics
              │  dispatcher  │   (Prometheus)   (JSON snapshot)
              └┬───┬───┬───┬─┘
     sync ────┘   │   │   └──── async (bounded queue, 1 worker, drop-oldest)
   stdout  sqlite  prometheus       webhook   otlp   <your sink>
   (JSON)  (query API)  (marker)   (batched POST) (OTLP/HTTP)
```

| Signal | Facade call | Use for |
|--------|-------------|---------|
| **Metric** | `count` / `gauge` / `observe` | rates, saturation, latency distributions |
| **Event** | `event(kind, **fields)` | discrete domain facts ("question.answered", "auth.login.failed") |
| **Span** | `with span(name) as s:` | timing a step of a pipeline; nested; correlated by request id |

Guarantees:

- **Registry is always on** (when `OBSERVABILITY_ENABLED`), independent of sinks —
  so `/metrics` and the JSON snapshot always work.
- **Never raises into the request path** — every sink call is guarded; the async
  queue drops oldest on overload and counts it (`queue_dropped`).
- **Disabled = cheap no-op** — every facade call returns immediately.
- **Correlation is automatic** — the HTTP middleware binds `request_id` +
  `route`; `get_principal` binds `tenant` + `actor`; spans and events pick them
  up without being passed around.

---

## 2. Sinks

Selected by `OBSERVABILITY_SINKS` (comma list). Built-in:

| Sink | What it does | Notes |
|------|--------------|-------|
| `noop` | nothing | the safe default / template |
| `stdout` | one JSON line per signal to the logger | pair with any log shipper; metrics opt-in (`OBS_STDOUT_METRICS`) |
| `sqlite` | events + spans to a **separate** DB (`{DATA_DIR}/observability.db`) | powers the events/traces APIs + UI; time-based retention |
| `prometheus` | marker → enables `GET /metrics` | registry is rendered on scrape; optional `OBS_PROMETHEUS_TOKEN` |
| `webhook` | batched NDJSON `POST` to `OBS_WEBHOOK_URL` | async, off-thread |
| `otlp` | OTLP/HTTP JSON span export to `OBS_OTLP_ENDPOINT` | experimental, dependency-free; spans only |
| `postgres` | batched INSERT of events/spans into one table (`OBS_POSTGRES_TABLE`) | centralized SQL log store; `psycopg` imported only if selected; `OBS_POSTGRES_DSN` |
| `mongodb` | batched `insert_many` of events/spans into one collection | centralized NoSQL log store; `pymongo` imported only if selected; `OBS_MONGO_URI` |

`postgres` / `mongodb` are the **centralized log collection** backends —
config-selected per deployment. The bundled `docker-compose.yml` `postgres` /
`mongodb` services are opt-in (`docker compose --profile postgres up -d`);
point the DSN/URI at any other instance instead. See
[`LOGGING.md`](LOGGING.md).

### Add your own (the "mould it" seam)

```python
# app/observability/sinks/mine.py
from .base import Sink

class MySink(Sink):
    name = "mine"
    blocking = True                       # if it does network / slow I/O
    def on_event(self, e):  ...
    def on_metric(self, s): ...
    def on_span(self, sp):  ...

# app/observability/sinks/__init__.py
SINK_BUILDERS["mine"] = lambda s: MySink(url=s.obs_mine_url)
```

Then `OBSERVABILITY_SINKS=stdout,mine`. Nothing else changes — not the facade,
not a single call site.

---

## 3. Configuration

| Env var | Default | Meaning |
|---------|---------|---------|
| `OBSERVABILITY_ENABLED` | `true` | master switch |
| `OBSERVABILITY_SINKS` | `stdout,sqlite,prometheus` | active sinks |
| `OBSERVABILITY_SERVICE_NAME` | `knowledgedesk` | resource/service label |
| `OBSERVABILITY_SAMPLE_TRACES` | `1.0` | span sampling 0..1 |
| `OBSERVABILITY_MAX_SERIES` | `2000` | per-metric label-set cap (memory guard) |
| `OBSERVABILITY_HEALTH_PROBE_SECONDS` | `30` | background dependency probe; `0` disables |
| `OBS_STDOUT_PRETTY` / `OBS_STDOUT_METRICS` | `false` | stdout sink options |
| `OBS_SQLITE_PATH` / `OBS_SQLITE_RETENTION_HOURS` | `{DATA_DIR}/observability.db` / `168` | sqlite sink |
| `OBS_PROMETHEUS_PATH` / `OBS_PROMETHEUS_TOKEN` | `/metrics` / _(none)_ | Prometheus endpoint |
| `OBS_WEBHOOK_URL` / `OBS_WEBHOOK_TOKEN` / `OBS_WEBHOOK_BATCH` | — / — / `100` | webhook sink |
| `OBS_OTLP_ENDPOINT` / `OBS_OTLP_HEADERS` | — / — | OTLP sink (`k=v,k2=v2` headers) |
| `OBS_POSTGRES_DSN` / `OBS_POSTGRES_TABLE` / `OBS_POSTGRES_BATCH` | — / `kd_logs` / `50` | postgres sink |
| `OBS_MONGO_URI` / `OBS_MONGO_DB` / `OBS_MONGO_COLLECTION` / `OBS_MONGO_BATCH` | — / `knowledgedesk` / `logs` / `50` | mongodb sink |
| `LOG_LEVEL` / `LOG_FORMAT` / `LOG_BRIDGE_LEVEL` | `INFO` / `json` / `WARNING` | structured stdlib logging + the WARNING→event bridge ([LOGGING.md](LOGGING.md)) |

**Client scenarios**

- *Nothing / air-gapped*: `OBSERVABILITY_SINKS=sqlite` → self-contained, queryable in the UI.
- *Prometheus + Grafana*: `OBSERVABILITY_SINKS=prometheus,sqlite`, scrape `/metrics`.
- *OpenTelemetry*: `OBSERVABILITY_SINKS=otlp,prometheus`, `OBS_OTLP_ENDPOINT=http://collector:4318`.
- *SIEM / data lake*: `OBSERVABILITY_SINKS=webhook`, point `OBS_WEBHOOK_URL` at their intake.
- *Already runs Postgres*: `OBSERVABILITY_SINKS=stdout,postgres`, set `OBS_POSTGRES_DSN` — a centralized, queryable SQL log store, cross-instance.
- *Already runs MongoDB*: `OBSERVABILITY_SINKS=stdout,mongodb`, set `OBS_MONGO_URI` — same, NoSQL.
- *Their bespoke stack*: implement a sink (§2).

---

## 4. What is instrumented

| Area | Metrics | Spans | Events |
|------|---------|-------|--------|
| HTTP (middleware) | `http.server.requests`, `http.server.duration.seconds`, `http.server.in_flight` | — | `http.request` |
| RAG | `rag.answers{mode,streamed}`, `rag.answer.seconds`, `rag.stage.seconds{stage}`, `rag.retrieval.hits`, `rag.llm.failures` | `rag.answer` › `rag.embed_query` / `rag.vector_search` / `rag.rerank` / `rag.llm_generate` | `question.answered`, `question.not_found` |
| Ingestion | `ingest.documents{outcome}`, `ingest.document.seconds`, `ingest.document.chunks`, `ingest.stage.seconds{stage}` | `ingest.document` › `parse` / `chunk` / `embed` / `upsert` | `document.ingested`, `document.ingest.failed` |
| Connectors | `connector.syncs{provider,status}` | — | `connector.sync.completed` |
| Auth | `auth.logins{outcome}`, `auth.refresh.reuse_detected` | — | `auth.login`, `auth.login.failed`, `auth.refresh.reuse_detected` |
| LLM / embeddings | `llm.calls{provider,outcome}`, `llm.generate.seconds`, `llm.response.chars`, `embedding.calls`, `embedding.batch.seconds`, `embedding.batch.texts` | — | — |
| Dependencies | `dependency.up{dependency}` (background probe + on `/api/health`) | — | — |
| Any span | `span.duration.seconds{span,status}` (so traces yield metrics even with no trace sink) | — | — |

---

## 5. Read APIs

| Method | Path | Permission | Notes |
|--------|------|-----------|-------|
| GET | `/metrics` | none¹ | Prometheus text; only if `prometheus` sink on; `OBS_PROMETHEUS_TOKEN` optional |
| GET | `/api/observability/config` | `observability.read` | active sinks, sample rate, drop count |
| GET | `/api/observability/metrics` | `observability.read` | JSON registry snapshot |
| GET | `/api/observability/events?kind=&since_seconds=&limit=` | `observability.read` | recent domain events (`sqlite` sink) |
| GET | `/api/observability/traces/{request_id}` | `observability.read` | spans for one request (`sqlite` sink) |

¹ typically scraped from inside the cluster; add `OBS_PROMETHEUS_TOKEN` to require a bearer.

**Scoping.** `observability.read` is held by `tenant_admin`, `service` and
`superadmin`. Tenant-scoped principals see only series / events / spans labelled
with their workspace (plus unlabelled infra metrics); superadmin sees everything.
It is *operational telemetry*, not workspace content, so `superadmin` holding it
does not violate the "no workspace content" rule — no document text or answers
are exposed.

UI: **/observability** — request rate / latency percentiles / error rate, RAG
stage timings, answer outcomes, ingest throughput, dependency health, a recent
events table, and a request-id → trace lookup.

---

## 6. Source

```
backend/app/observability/
  __init__.py     facade: count / gauge / observe / event / span / bound / snapshot / setup / shutdown
  models.py       Sample · Event · Span
  context.py      request_id / tenant / actor / span-stack contextvars
  registry.py     in-process aggregation + Prometheus renderer
  dispatcher.py   fan-out; sync inline, blocking sinks off-thread
  middleware.py   HTTP instrumentation
  sinks/
    base.py       the Sink contract
    __init__.py   SINK_BUILDERS registry  ← extension point
    noop / stdout / sqlite / prometheus / webhook / otlp .py
backend/app/routers/observability.py   read APIs
backend/app/main.py                     obs.setup(), middleware, /metrics, health probe
backend/tests/test_observability.py
frontend/src/app/(dashboard)/observability/page.tsx
frontend/src/lib/api/observability.ts
```

Instrumentation call sites: `services/rag.py`, `services/ingestion.py`,
`services/llm.py`, `services/embeddings.py`, `routers/auth_routes.py`,
`routers/connectors.py`, `auth.py` (`_bind_observability`).
