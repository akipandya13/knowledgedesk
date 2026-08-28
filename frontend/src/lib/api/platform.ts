"use client";

import { apiFetch } from "./client";
import type { AuditEntry, TenantRow } from "@/lib/types";

export interface PlatformStats {
  tenants: number;
  users: number;
  documents: number;
  queries_total: number;
}

export function getPlatformStats() {
  return apiFetch<PlatformStats>("/admin/platform/stats");
}

export function getPlatformAudit(limit = 200) {
  return apiFetch<AuditEntry[]>(`/admin/platform/audit?limit=${limit}`);
}

export function listTenants() {
  return apiFetch<TenantRow[]>("/admin/tenants");
}

export function createTenant(name: string, slug: string) {
  return apiFetch<{ slug: string; name: string; api_key: string; id: number }>("/admin/tenants", {
    method: "POST",
    body: { name, slug },
  });
}

export function deleteTenant(slug: string) {
  return apiFetch<{ deleted: string }>(`/admin/tenants/${slug}`, { method: "DELETE" });
}
