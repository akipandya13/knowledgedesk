"use client";

import { API_PREFIX } from "@/lib/config";
import { getAccess } from "@/lib/auth/tokenStore";
import { apiFetch } from "./client";
import type {
  ActivityEntry,
  ActivityFilter,
  AdminStats,
  AuditEntry,
  AuditFilter,
  AuditVerifyResult,
  EffectiveConfig,
  KnowledgeGap,
  ModelCatalog,
  RecentQuery,
} from "@/lib/types";

function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

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

export function getTenantAudit(filter: AuditFilter = {}) {
  return apiFetch<AuditEntry[]>(
    `/admin/audit${qs({ limit: filter.limit ?? 100, prefix: filter.prefix,
      actor: filter.actor, target_type: filter.target_type, since: filter.since,
      until: filter.until, before_id: filter.before_id })}`,
  );
}

export function verifyTenantAudit() {
  return apiFetch<AuditVerifyResult>("/admin/audit/verify");
}

/** Tamper-evident change timeline for one entity (user, workspace_settings,
 *  model_connector, data_connector, role, api_key, …). */
export function getAuditHistory(targetType: string, targetId: string | number, limit = 100) {
  return apiFetch<AuditEntry[]>(
    `/admin/audit/history${qs({ target_type: targetType, target_id: String(targetId), limit })}`,
  );
}

export function getActivity(filter: ActivityFilter = {}) {
  return apiFetch<ActivityEntry[]>(
    `/admin/activity${qs({ limit: filter.limit ?? 100, user_id: filter.user_id,
      prefix: filter.prefix, category: filter.category, actor: filter.actor,
      target_type: filter.target_type, since: filter.since, until: filter.until,
      before_id: filter.before_id })}`,
  );
}

/** Trigger a browser download of the audit or activity log as CSV. The fetch
 *  carries the bearer token; the response is streamed straight to a blob. */
export async function downloadLogCsv(
  kind: "audit" | "activity",
  filter: AuditFilter & ActivityFilter = {},
): Promise<void> {
  const path = `/admin/${kind}${qs({ format: "csv", limit: filter.limit ?? 1000,
    user_id: filter.user_id, prefix: filter.prefix, category: filter.category,
    actor: filter.actor, target_type: filter.target_type, since: filter.since,
    until: filter.until })}`;
  const res = await fetch(`${API_PREFIX}${path}`, {
    headers: { Authorization: `Bearer ${getAccess()}` },
  });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${kind}-log.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
