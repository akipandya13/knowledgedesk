// Client-side mirror of backend/app/rbac.py. The backend is always the
// authority — this only decides what to *show*. Keep the matrix in sync.

import type { Permission, Role } from "@/lib/types";

const MEMBER: Permission[] = [
  "query.run",
  "feedback.write",
  "document.read",
  "document.write.workspace",
  "insights.read",
  "settings.read",
];

const TENANT_ADMIN: Permission[] = [
  ...MEMBER,
  "document.write.tenant",
  "document.delete",
  "settings.write",
  "model_connector.manage",
  "data_connector.manage",
  "audit.read",
  "activity.read",
  "observability.read",
  "access.manage",
  "user.manage",
];

// API keys act for a workspace but never manage humans.
const SERVICE: Permission[] = TENANT_ADMIN.filter((p) => p !== "user.manage");

// Platform operator: no workspace-content permissions, but does get the
// operational telemetry it needs to run the platform.
const SUPERADMIN: Permission[] = [
  "observability.read",
  "user.manage",
  "tenant.manage",
  "platform.read",
];

export const ROLE_PERMISSIONS: Record<Role, ReadonlySet<Permission>> = {
  member: new Set(MEMBER),
  tenant_admin: new Set(TENANT_ADMIN),
  service: new Set(SERVICE),
  superadmin: new Set(SUPERADMIN),
};

export function can(
  user: { role: Role } | null | undefined,
  permission: Permission,
): boolean {
  if (!user) return false;
  return ROLE_PERMISSIONS[user.role]?.has(permission) ?? false;
}

export function canAny(
  user: { role: Role } | null | undefined,
  permissions: Permission[],
): boolean {
  return permissions.some((p) => can(user, p));
}
