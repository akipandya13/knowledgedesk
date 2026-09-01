"use client";

import { apiFetch } from "./client";
import type { AuthSession, CurrentUser, LoginResult, TokenPair } from "@/lib/types";

export function login(email: string, password: string) {
  return apiFetch<LoginResult>("/auth/login", {
    method: "POST",
    body: { email, password },
    anonymous: true,
    noRetry: true,
  });
}

export function loginMfa(mfa_token: string, code: string) {
  return apiFetch<TokenPair>("/auth/login/mfa", {
    method: "POST",
    body: { mfa_token, code },
    anonymous: true,
    noRetry: true,
  });
}

export function me() {
  return apiFetch<CurrentUser>("/auth/me");
}

export function logout(refresh_token: string) {
  return apiFetch<{ ok: boolean }>("/auth/logout", { method: "POST", body: { refresh_token } });
}

export function changePassword(current_password: string, new_password: string) {
  return apiFetch<{ ok: boolean; note: string }>("/auth/change-password", {
    method: "POST",
    body: { current_password, new_password },
  });
}

// ── password reset / email verification ──────────────────────────
export const forgotPassword = (email: string) =>
  apiFetch<{ ok: boolean; note: string }>("/auth/password/forgot", {
    method: "POST", body: { email }, anonymous: true,
  });
export const resetPassword = (token: string, new_password: string) =>
  apiFetch<{ ok: boolean; note: string }>("/auth/password/reset", {
    method: "POST", body: { token, new_password }, anonymous: true,
  });
export const verifyEmail = (token: string) =>
  apiFetch<{ ok: boolean }>("/auth/email/verify", { method: "POST", body: { token }, anonymous: true });
export const resendVerification = () =>
  apiFetch<{ ok: boolean; note?: string }>("/auth/email/resend", { method: "POST" });

// ── TOTP MFA ─────────────────────────────────────────────────────
export const mfaSetup = () =>
  apiFetch<{ secret: string; otpauth_uri: string }>("/auth/mfa/setup", { method: "POST" });
export const mfaEnable = (code: string) =>
  apiFetch<{ ok: boolean; recovery_codes: string[]; note: string }>("/auth/mfa/enable", {
    method: "POST", body: { code },
  });
export const mfaDisable = (body: { password?: string; code?: string }) =>
  apiFetch<{ ok: boolean }>("/auth/mfa/disable", { method: "POST", body });
export const mfaRegenCodes = () =>
  apiFetch<{ recovery_codes: string[]; note: string }>("/auth/mfa/recovery-codes", { method: "POST" });

// ── sessions ─────────────────────────────────────────────────────
export const listSessions = () => apiFetch<AuthSession[]>("/auth/sessions");
export const revokeSession = (id: number) =>
  apiFetch<{ revoked: number }>(`/auth/sessions/${id}`, { method: "DELETE" });
export const revokeAllSessions = () =>
  apiFetch<{ revoked: number; note: string }>("/auth/sessions", { method: "DELETE" });

// ── SSO ──────────────────────────────────────────────────────────
export const ssoLookup = (email: string) =>
  apiFetch<{ available: boolean; entitled?: boolean; display_name?: string; start_url?: string }>(
    `/auth/sso/lookup?email=${encodeURIComponent(email)}`,
    { anonymous: true },
  );
