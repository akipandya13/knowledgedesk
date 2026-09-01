"use client";

import { apiFetch } from "./client";
import type { Role, UserRow } from "@/lib/types";

export function listUsers(tenantSlug?: string) {
  const suffix = tenantSlug ? `?tenant=${encodeURIComponent(tenantSlug)}` : "";
  return apiFetch<UserRow[]>(`/users${suffix}`);
}

export interface CreateUserBody {
  email: string;
  full_name?: string;
  role: Role;
  password?: string;
  tenant_slug?: string;
}

export function createUser(body: CreateUserBody) {
  return apiFetch<UserRow & { temporary_password?: string }>("/users", { method: "POST", body });
}

export function updateUser(
  id: number,
  body: { full_name?: string; role?: Role; is_active?: boolean; clearance?: number },
) {
  return apiFetch<UserRow>(`/users/${id}`, { method: "PATCH", body });
}

export function resetPassword(id: number) {
  return apiFetch<{ temporary_password: string; note: string }>(
    `/users/${id}/reset-password`,
    { method: "POST" },
  );
}
