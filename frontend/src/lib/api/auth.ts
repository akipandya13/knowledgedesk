"use client";

import { apiFetch } from "./client";
import type { CurrentUser, TokenPair } from "@/lib/types";

export function login(email: string, password: string) {
  return apiFetch<TokenPair>("/auth/login", {
    method: "POST",
    body: { email, password },
    anonymous: true,
    noRetry: true,
  });
}

export function me() {
  return apiFetch<CurrentUser>("/auth/me");
}

export function logout(refresh_token: string) {
  return apiFetch<{ ok: boolean }>("/auth/logout", {
    method: "POST",
    body: { refresh_token },
  });
}

export function changePassword(current_password: string, new_password: string) {
  return apiFetch<{ ok: boolean; note: string }>("/auth/change-password", {
    method: "POST",
    body: { current_password, new_password },
  });
}
