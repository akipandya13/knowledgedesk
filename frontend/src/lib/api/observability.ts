"use client";

import { apiFetch } from "./client";
import type { MetricsSnapshot, ObsConfig, ObsEvent, ObsSpan, SloReport } from "@/lib/types";

export function getObsConfig() {
  return apiFetch<ObsConfig>("/observability/config");
}

export function getSlo() {
  return apiFetch<SloReport>("/observability/slo");
}

export function getMetricsSnapshot() {
  return apiFetch<MetricsSnapshot>("/observability/metrics");
}

export function getObsEvents(params: { kind?: string; sinceSeconds?: number; limit?: number } = {}) {
  const qs = new URLSearchParams();
  if (params.kind) qs.set("kind", params.kind);
  if (params.sinceSeconds) qs.set("since_seconds", String(params.sinceSeconds));
  if (params.limit) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiFetch<{ events: ObsEvent[]; count: number }>(`/observability/events${suffix}`);
}

export function getTrace(requestId: string) {
  return apiFetch<{ request_id: string; spans: ObsSpan[] }>(
    `/observability/traces/${encodeURIComponent(requestId)}`,
  );
}
