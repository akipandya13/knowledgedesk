// Client-side constants. All API calls are same-origin under /api (Next rewrites
// proxy them to the backend), so there is no base URL to configure here.

export const API_PREFIX = "/api";

export const STORAGE_KEYS = {
  access: "kd_access",
  refresh: "kd_refresh",
  user: "kd_user",
} as const;

export const ROLE_HOME: Record<string, string> = {
  superadmin: "/platform/overview",
  tenant_admin: "/ask",
  member: "/ask",
  service: "/ask",
};
