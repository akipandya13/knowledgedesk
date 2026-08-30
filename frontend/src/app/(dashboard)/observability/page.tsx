"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getMetricsSnapshot,
  getObsConfig,
  getObsEvents,
  getTrace,
} from "@/lib/api/observability";
import type { Metric, MetricsSnapshot, ObsConfig, ObsEvent, ObsSpan } from "@/lib/types";
import { Card, Empty, Loading, Notice, PageHeader, StatCard, TableWrap } from "@/components/ui";
import { useToast } from "@/components/Toast";

const REFRESH_MS = 10_000;

// ── snapshot helpers ────────────────────────────────────────────
function metric(snap: MetricsSnapshot | null, name: string): Metric | undefined {
  return snap?.metrics.find((m) => m.name === name);
}
function sumCounter(snap: MetricsSnapshot | null, name: string, match?: (l: Record<string, string>) => boolean): number {
  const m = metric(snap, name);
  if (!m) return 0;
  return m.series
    .filter((s) => !match || match(s.labels))
    .reduce((acc, s) => acc + (s.value || 0), 0);
}
function gaugeVal(snap: MetricsSnapshot | null, name: string, match: (l: Record<string, string>) => boolean): number | null {
  const s = metric(snap, name)?.series.find((x) => match(x.labels));
  return s ? (s.value ?? null) : null;
}
/** p-quantile from cumulative histogram buckets across all series of a metric. */
function histQuantile(snap: MetricsSnapshot | null, name: string, q: number, match?: (l: Record<string, string>) => boolean): number | null {
  const m = metric(snap, name);
  if (!m) return null;
  const series = m.series.filter((s) => !match || match(s.labels));
  const total = series.reduce((a, s) => a + (s.count || 0), 0);
  if (!total) return null;
  // merge buckets
  const merged = new Map<number, number>();
  for (const s of series) {
    for (const [k, v] of Object.entries(s.buckets || {})) {
      const ub = Number(k);
      merged.set(ub, (merged.get(ub) || 0) + v);
    }
  }
  const bounds = [...merged.keys()].sort((a, b) => a - b);
  const want = q * total;
  for (const b of bounds) {
    if ((merged.get(b) || 0) >= want) return b;
  }
  return bounds.length ? bounds[bounds.length - 1] : null;
}
function ms(v: number | null): string {
  return v == null ? "—" : v < 1 ? `${Math.round(v * 1000)} ms` : `${v.toFixed(2)} s`;
}

export default function ObservabilityPage() {
  const { toast } = useToast();
  const [cfg, setCfg] = useState<ObsConfig | null>(null);
  const [snap, setSnap] = useState<MetricsSnapshot | null>(null);
  const [events, setEvents] = useState<ObsEvent[]>([]);
  const [traceId, setTraceId] = useState("");
  const [spans, setSpans] = useState<ObsSpan[] | null>(null);

  const load = useCallback(() => {
    Promise.all([getObsConfig(), getMetricsSnapshot(), getObsEvents({ limit: 60 })])
      .then(([c, s, e]) => {
        setCfg(c);
        setSnap(s);
        setEvents(e.events);
      })
      .catch((err) => toast(err instanceof Error ? err.message : "Load failed", "error"));
  }, [toast]);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const derived = useMemo(() => {
    const total = sumCounter(snap, "http.server.requests");
    const errs = sumCounter(snap, "http.server.requests", (l) => l.status_class === "5xx");
    const answers = sumCounter(snap, "rag.answers");
    const notFound = sumCounter(snap, "rag.answers", (l) => l.mode === "not_found");
    return {
      requests: total,
      errorPct: total ? (errs / total) * 100 : 0,
      p50: histQuantile(snap, "http.server.duration.seconds", 0.5),
      p95: histQuantile(snap, "http.server.duration.seconds", 0.95),
      answers,
      answerP95: histQuantile(snap, "rag.answer.seconds", 0.95),
      notFoundPct: answers ? (notFound / answers) * 100 : 0,
      ingested: sumCounter(snap, "ingest.documents", (l) => l.outcome === "ready"),
      ingestFailed: sumCounter(snap, "ingest.documents", (l) => l.outcome === "failed"),
      qdrant: gaugeVal(snap, "dependency.up", (l) => l.dependency === "qdrant"),
      llm: gaugeVal(snap, "dependency.up", (l) => l.dependency === "llm"),
    };
  }, [snap]);

  const stageRows = useMemo(() => {
    const m = metric(snap, "rag.stage.seconds");
    if (!m) return [];
    return m.series
      .map((s) => ({
        stage: s.labels.stage || "?",
        count: s.count || 0,
        avg: s.count ? (s.sum || 0) / s.count : 0,
      }))
      .sort((a, b) => b.avg - a.avg);
  }, [snap]);

  const modeRows = useMemo(() => {
    const m = metric(snap, "rag.answers");
    if (!m) return [];
    const agg = new Map<string, number>();
    for (const s of m.series) agg.set(s.labels.mode || "?", (agg.get(s.labels.mode || "?") || 0) + (s.value || 0));
    return [...agg.entries()].sort((a, b) => b[1] - a[1]);
  }, [snap]);

  async function lookupTrace() {
    if (!traceId.trim()) return;
    try {
      const r = await getTrace(traceId.trim());
      setSpans(r.spans);
    } catch (e) {
      setSpans([]);
      toast(e instanceof Error ? e.message : "No trace", "warning");
    }
  }

  if (!cfg || !snap) return <Loading label="Loading telemetry…" />;

  return (
    <>
      <PageHeader
        title="Observability"
        subtitle="Live metrics, domain events and request traces. Signals also flow to the configured sinks."
      />

      {!cfg.enabled && <Notice kind="amber">Observability is disabled (OBSERVABILITY_ENABLED=false).</Notice>}

      <Card title="Pipeline" style={{ marginBottom: 16 }}>
        <div className="chips">
          <span className="chip" style={{ cursor: "default" }}>service · {cfg.service}</span>
          {cfg.sinks.map((s) => (
            <span key={s} className="chip active" style={{ cursor: "default" }}>sink · {s}</span>
          ))}
          <span className="chip" style={{ cursor: "default" }}>trace sample · {Math.round(cfg.trace_sample_rate * 100)}%</span>
          {cfg.queue_dropped > 0 && (
            <span className="chip" style={{ cursor: "default", color: "var(--red)" }}>dropped · {cfg.queue_dropped}</span>
          )}
        </div>
      </Card>

      <div className="stat-grid">
        <StatCard value={derived.requests} label="HTTP requests" />
        <StatCard value={`${derived.errorPct.toFixed(1)}%`} label="5xx rate" />
        <StatCard value={ms(derived.p50)} label="Latency p50" />
        <StatCard value={ms(derived.p95)} label="Latency p95" />
        <StatCard value={derived.answers} label="Answers" />
        <StatCard value={ms(derived.answerP95)} label="Answer p95" />
        <StatCard value={`${derived.notFoundPct.toFixed(0)}%`} label="Not-found rate" />
        <StatCard value={`${derived.ingested}/${derived.ingested + derived.ingestFailed}`} label="Docs ingested ok" />
        <StatCard value={derived.qdrant == null ? "—" : derived.qdrant ? "up" : "down"} label="Qdrant" />
        <StatCard value={derived.llm == null ? "—" : derived.llm ? "up" : "down"} label="LLM backend" />
      </div>

      <div className="two-col" style={{ marginTop: 16 }}>
        <Card title="RAG stage latency (avg)">
          {stageRows.length === 0 ? (
            <Empty>No answers recorded yet.</Empty>
          ) : (
            <TableWrap head={<><th>Stage</th><th>Calls</th><th>Avg</th></>}>
              {stageRows.map((r) => (
                <tr key={r.stage}>
                  <td style={{ fontWeight: 600 }}>{r.stage}</td>
                  <td>{r.count}</td>
                  <td>{ms(r.avg)}</td>
                </tr>
              ))}
            </TableWrap>
          )}
        </Card>

        <Card title="Answers by outcome">
          {modeRows.length === 0 ? (
            <Empty>No answers yet.</Empty>
          ) : (
            <TableWrap head={<><th>Mode</th><th>Count</th></>}>
              {modeRows.map(([mode, n]) => (
                <tr key={mode}>
                  <td style={{ fontWeight: 600 }}>{mode}</td>
                  <td>{n}</td>
                </tr>
              ))}
            </TableWrap>
          )}
        </Card>
      </div>

      <Card title="Request trace lookup" style={{ margin: "16px 0" }}>
        <div className="row">
          <input
            value={traceId}
            onChange={(e) => setTraceId(e.target.value)}
            placeholder="X-Request-ID from a response header"
            style={{ flex: 1 }}
          />
          <button className="btn" onClick={lookupTrace}>Load trace</button>
        </div>
        {spans && (
          spans.length === 0 ? (
            <Empty>No spans for that request id.</Empty>
          ) : (
            <TableWrap head={<><th>Span</th><th>Status</th><th>Duration</th></>}>
              {spans.map((s) => (
                <tr key={s.span_id}>
                  <td style={{ paddingLeft: s.parent_id ? 20 : 0, fontWeight: s.parent_id ? 400 : 600 }}>
                    {s.name}
                  </td>
                  <td style={{ color: s.status === "error" ? "var(--red)" : undefined }}>{s.status}</td>
                  <td>{s.duration_ms == null ? "—" : `${s.duration_ms.toFixed(1)} ms`}</td>
                </tr>
              ))}
            </TableWrap>
          )
        )}
      </Card>

      <div className="card-title">Recent events</div>
      {events.length === 0 ? (
        <Empty>No events recorded (is the `sqlite` sink enabled?).</Empty>
      ) : (
        <TableWrap head={<><th>When</th><th>Kind</th><th>Tenant</th><th>Actor</th><th>Detail</th></>}>
          {events.map((e, i) => (
            <tr key={i}>
              <td className="small muted">{new Date(e.ts * 1000).toLocaleTimeString()}</td>
              <td style={{ color: e.level === "error" ? "var(--red)" : e.level === "warn" ? "var(--amber, #b45309)" : undefined }}>
                {e.kind}
              </td>
              <td className="small">{e.tenant || "—"}</td>
              <td className="small">{e.actor || "—"}</td>
              <td className="small mono" style={{ maxWidth: 380, overflow: "hidden", textOverflow: "ellipsis" }}>
                {JSON.stringify(e.fields)}
              </td>
            </tr>
          ))}
        </TableWrap>
      )}
    </>
  );
}
