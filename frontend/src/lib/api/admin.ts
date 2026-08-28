"use client";

import { apiFetch } from "./client";
import type {
  AdminStats,
  AuditEntry,
  EffectiveConfig,
  KnowledgeGap,
  ModelCatalog,
  RecentQuery,
} from "@/lib/types";

export function getStats() {
  return apiFetch<AdminStats>("/admin/stats");
}

export function getRecentQueries(limit = 50) {
  return apiFetch<RecentQuery[]>(`/admin/queries?limit=${limit}`);
}

export function getGaps(limit = 50) {
  return apiFetch<KnowledgeGap[]>(`/admin/gaps?limit=${limit}`);
}

export function getModelCatalog() {
  return apiFetch<ModelCatalog>("/admin/model-catalog");
}

export function getEffectiveConfig() {
  return apiFetch<EffectiveConfig>("/admin/config");
}

export function updateSettings(settings: Record<string, unknown>) {
  return apiFetch<{ settings: Record<string, unknown>; effective: Record<string, unknown>; note: string | null }>(
    "/admin/settings",
    { method: "PUT", body: { settings } },
  );
}

export function getReadiness() {
  return apiFetch<Record<string, unknown>>("/admin/readiness");
}

export function getTenantAudit(limit = 100) {
  return apiFetch<AuditEntry[]>(`/admin/audit?limit=${limit}`);
}
