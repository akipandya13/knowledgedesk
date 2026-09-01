"use client";

import { apiFetch } from "./client";
import type {
  AccessCatalog,
  AccessGroup,
  ApiKeyRow,
  AuthPolicy,
  CustomRole,
  GrantEffect,
  MyAccess,
  ResourceGrantRow,
  SsoConfig,
  SubjectAssignments,
  SubjectType,
} from "@/lib/types";

export const getMyAccess = () => apiFetch<MyAccess>("/access/me");
export const getAccessCatalog = () => apiFetch<AccessCatalog>("/access/catalog");

export const getRoles = () => apiFetch<CustomRole[]>("/access/roles");
export const createRole = (body: { key: string; name?: string; description?: string; permissions: string[] }) =>
  apiFetch<CustomRole>("/access/roles", { method: "POST", body });
export const updateRole = (id: number, body: { name?: string; description?: string; permissions?: string[] }) =>
  apiFetch<CustomRole>(`/access/roles/${id}`, { method: "PATCH", body });
export const deleteRole = (id: number) =>
  apiFetch<{ deleted: number }>(`/access/roles/${id}`, { method: "DELETE" });

export const getGroups = () => apiFetch<AccessGroup[]>("/access/groups");
export const createGroup = (body: { name: string; description?: string }) =>
  apiFetch<AccessGroup>("/access/groups", { method: "POST", body });
export const deleteGroup = (id: number) =>
  apiFetch<{ deleted: number }>(`/access/groups/${id}`, { method: "DELETE" });
export const addGroupMember = (groupId: number, userId: number) =>
  apiFetch<AccessGroup>(`/access/groups/${groupId}/members`, { method: "POST", body: { user_id: userId } });
export const removeGroupMember = (groupId: number, userId: number) =>
  apiFetch<AccessGroup>(`/access/groups/${groupId}/members/${userId}`, { method: "DELETE" });

export const getAssignments = (subjectType: SubjectType, subjectId: number) =>
  apiFetch<SubjectAssignments>(`/access/assignments?subject_type=${subjectType}&subject_id=${subjectId}`);
export const assignRole = (subjectType: SubjectType, subjectId: number, roleId: number) =>
  apiFetch<{ ok: boolean }>("/access/role-assignments", {
    method: "POST",
    body: { subject_type: subjectType, subject_id: subjectId, role_id: roleId },
  });
export const unassignRole = (assignmentId: number) =>
  apiFetch<{ deleted: number }>(`/access/role-assignments/${assignmentId}`, { method: "DELETE" });

export const setGrant = (body: {
  subject_type: SubjectType;
  subject_id: number;
  permission: string;
  effect: GrantEffect;
  note?: string;
}) => apiFetch<{ id: number }>("/access/grants", { method: "POST", body });
export const deleteGrant = (id: number) =>
  apiFetch<{ deleted: number }>(`/access/grants/${id}`, { method: "DELETE" });

export const getResourceGrants = (resourceType: string, resourceId: string) =>
  apiFetch<ResourceGrantRow[]>(
    `/access/resource-grants?resource_type=${resourceType}&resource_id=${encodeURIComponent(resourceId)}`,
  );
export const setResourceGrant = (body: {
  subject_type: SubjectType;
  subject_id: number;
  resource_type: string;
  resource_id: string;
  permission: string;
}) => apiFetch<{ id: number }>("/access/resource-grants", { method: "POST", body });
export const deleteResourceGrant = (id: number) =>
  apiFetch<{ deleted: number }>(`/access/resource-grants/${id}`, { method: "DELETE" });

export const getPolicy = () => apiFetch<{ confidentiality_enforced: boolean }>("/access/policy");
export const setPolicy = (confidentiality_enforced: boolean) =>
  apiFetch<{ confidentiality_enforced: boolean }>("/access/policy", {
    method: "PUT",
    body: { confidentiality_enforced },
  });

export const effectiveFor = (userId: number) =>
  apiFetch<{ user_id: number; email: string; base_role: string; permissions: string[] }>(
    `/access/effective/${userId}`,
  );

// ── authentication policy ──────────────────────────────────────
export const getAuthPolicy = () => apiFetch<AuthPolicy>("/access/auth-policy");
export const setAuthPolicy = (body: { mfa_required?: boolean; require_verified_email?: boolean }) =>
  apiFetch<AuthPolicy>("/access/auth-policy", { method: "PUT", body });

// ── API keys ──────────────────────────────────────────────────
export const listApiKeys = () => apiFetch<ApiKeyRow[]>("/access/api-keys");
export const createApiKey = (name: string, expires_in_days?: number) =>
  apiFetch<ApiKeyRow & { api_key: string; note: string }>("/access/api-keys", {
    method: "POST",
    body: { name, expires_in_days },
  });
export const revokeApiKey = (id: number) =>
  apiFetch<{ revoked: number }>(`/access/api-keys/${id}`, { method: "DELETE" });

// ── SSO ───────────────────────────────────────────────────────
export const getSso = () => apiFetch<SsoConfig>("/access/sso");
export const putSso = (body: {
  display_name: string;
  issuer: string;
  client_id: string;
  client_secret?: string | null;
  allowed_domains: string[];
  default_role: string;
  is_active: boolean;
}) => apiFetch<SsoConfig>("/access/sso", { method: "PUT", body });
export const deleteSso = () => apiFetch<{ deleted: boolean }>("/access/sso", { method: "DELETE" });
