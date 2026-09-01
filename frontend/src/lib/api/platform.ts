"use client";

import { apiFetch } from "./client";
import type {
  AuditEntry,
  TenantCreateResult,
  TenantDetail,
  TenantRow,
} from "@/lib/types";

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

export function getTenant(slug: string) {
  return apiFetch<TenantDetail>(`/admin/tenants/${slug}`);
}

export interface CreateTenantInput {
  name: string;
  slug: string;
  admin_email?: string;
  admin_full_name?: string;
  entitlements?: string[];
}

export function createTenant(input: CreateTenantInput) {
  return apiFetch<TenantCreateResult>("/admin/tenants", { method: "POST", body: input });
}

export function updateTenant(
  slug: string,
  patch: { name?: string; entitlements?: string[] },
) {
  return apiFetch<TenantDetail>(`/admin/tenants/${slug}`, { method: "PATCH", body: patch });
}

export function suspendTenant(slug: string, reason: string) {
  return apiFetch<TenantDetail>(`/admin/tenants/${slug}/suspend`, {
    method: "POST",
    body: { reason },
  });
}

export function reactivateTenant(slug: string) {
  return apiFetch<TenantDetail>(`/admin/tenants/${slug}/reactivate`, { method: "POST" });
}

export function deleteTenant(slug: string) {
  return apiFetch<{ deleted: string; rows_deleted: Record<string, number> }>(
    `/admin/tenants/${slug}`,
    { method: "DELETE" },
  );
}
