"use client";

import { STORAGE_KEYS } from "@/lib/config";
import type { CurrentUser } from "@/lib/types";

// Small wrapper around localStorage so token handling lives in one place and
// stays SSR-safe (all reads guarded by a window check).

export function getAccess(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(STORAGE_KEYS.access) || "";
}

export function getRefresh(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(STORAGE_KEYS.refresh) || "";
}

export function getStoredUser(): CurrentUser | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(STORAGE_KEYS.user);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as CurrentUser;
  } catch {
    return null;
  }
}

export function setSession(access: string, refresh: string, user: CurrentUser): void {
  window.localStorage.setItem(STORAGE_KEYS.access, access);
  window.localStorage.setItem(STORAGE_KEYS.refresh, refresh);
  window.localStorage.setItem(STORAGE_KEYS.user, JSON.stringify(user));
}

export function updateStoredUser(user: CurrentUser): void {
  window.localStorage.setItem(STORAGE_KEYS.user, JSON.stringify(user));
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEYS.access);
  window.localStorage.removeItem(STORAGE_KEYS.refresh);
  window.localStorage.removeItem(STORAGE_KEYS.user);
}
