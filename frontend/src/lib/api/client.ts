"use client";

import { API_PREFIX } from "@/lib/config";
import {
  clearSession,
  getAccess,
  getRefresh,
  setSession,
} from "@/lib/auth/tokenStore";
import type { TokenPair } from "@/lib/types";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type Body = unknown;

interface RequestOpts {
  method?: string;
  body?: Body;
  /** Skip the Bearer header (login / refresh). */
  anonymous?: boolean;
  /** Return the raw Response instead of parsed JSON (streaming, downloads). */
  raw?: boolean;
  /** Do not attempt a token refresh on 401 (used by the refresh call itself). */
  noRetry?: boolean;
  signal?: AbortSignal;
}

let refreshInFlight: Promise<boolean> | null = null;

function redirectToLogin(): void {
  clearSession();
  if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${next}`;
  }
}

async function doRefresh(): Promise<boolean> {
  const refresh_token = getRefresh();
  if (!refresh_token) return false;
  try {
    const res = await fetch(`${API_PREFIX}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token }),
    });
    if (!res.ok) return false;
    const data = (await res.json()) as TokenPair;
    setSession(data.access_token, data.refresh_token, data.user);
    return true;
  } catch {
    return false;
  }
}

function refreshOnce(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

export async function apiFetch<T = unknown>(
  path: string,
  opts: RequestOpts = {},
): Promise<T> {
  const { method = "GET", body, anonymous, raw, noRetry, signal } = opts;

  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const headers: Record<string, string> = {};
  if (!isForm && body !== undefined) headers["Content-Type"] = "application/json";
  if (!anonymous) {
    const token = getAccess();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const init: RequestInit = { method, headers, signal };
  if (body !== undefined) init.body = isForm ? (body as FormData) : JSON.stringify(body);

  let res = await fetch(`${API_PREFIX}${path}`, init);

  if (res.status === 401 && !anonymous && !noRetry) {
    const ok = await refreshOnce();
    if (!ok) {
      redirectToLogin();
      throw new ApiError(401, "Session expired");
    }
    const retryHeaders = { ...headers, Authorization: `Bearer ${getAccess()}` };
    res = await fetch(`${API_PREFIX}${path}`, { ...init, headers: retryHeaders });
    if (res.status === 401) {
      redirectToLogin();
      throw new ApiError(401, "Session expired");
    }
  }

  if (raw) {
    if (!res.ok) {
      const detail = await safeDetail(res);
      throw new ApiError(res.status, detail);
    }
    return res as unknown as T;
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail =
      (data && (data.detail as string)) || res.statusText || `Request failed (${res.status})`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

async function safeDetail(res: Response): Promise<string> {
  try {
    const data = await res.json();
    return (data && data.detail) || res.statusText;
  } catch {
    return res.statusText || `Request failed (${res.status})`;
  }
}
