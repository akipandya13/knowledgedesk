"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import * as authApi from "@/lib/api/auth";
import { getMyAccess } from "@/lib/api/access";
import {
  clearSession,
  getAccess,
  getRefresh,
  getStoredUser,
  setSession,
  updateStoredUser,
} from "./tokenStore";
import { can as roleCan } from "./permissions";
import type { CurrentUser, Permission, TokenPair } from "@/lib/types";

type SignInResult = { kind: "ok"; user: CurrentUser } | { kind: "mfa"; mfaToken: string };

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  /** Effective permissions from /api/access/me (custom roles + grants folded in). */
  permissions: ReadonlySet<string>;
  /** Prefer this over `can(user, …)` — it reflects fine-grained grants. */
  hasPermission: (p: Permission | string) => boolean;
  signIn: (email: string, password: string) => Promise<SignInResult>;
  completeMfa: (mfaToken: string, code: string) => Promise<CurrentUser>;
  establish: (pair: TokenPair) => CurrentUser;
  /** Adopt a session from raw tokens (SSO redirect) — fetches the profile. */
  establishFromTokens: (access: string, refresh: string) => Promise<CurrentUser>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
  setUser: (u: CurrentUser) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);
AuthContext.displayName = "AuthContext";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [permissions, setPermissions] = useState<ReadonlySet<string>>(new Set());

  const loadPermissions = useCallback(() => {
    getMyAccess()
      .then((a) => setPermissions(new Set(a.permissions)))
      .catch(() => setPermissions(new Set()));
  }, []);

  useEffect(() => {
    const stored = getStoredUser();
    if (stored && getAccess()) {
      setUserState(stored);
      loadPermissions();
      // Revalidate in the background; ignore failures (client.ts handles 401).
      authApi
        .me()
        .then((fresh) => {
          setUserState(fresh);
          updateStoredUser(fresh);
        })
        .catch(() => undefined)
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [loadPermissions]);

  const establish = useCallback((pair: TokenPair): CurrentUser => {
    setSession(pair.access_token, pair.refresh_token, pair.user);
    setUserState(pair.user);
    loadPermissions();
    return pair.user;
  }, [loadPermissions]);

  const signIn = useCallback(async (email: string, password: string): Promise<SignInResult> => {
    const res = await authApi.login(email, password);
    if ("mfa_required" in res) return { kind: "mfa", mfaToken: res.mfa_token };
    return { kind: "ok", user: establish(res) };
  }, [establish]);

  const completeMfa = useCallback(async (mfaToken: string, code: string) => {
    const pair = await authApi.loginMfa(mfaToken, code);
    return establish(pair);
  }, [establish]);

  const establishFromTokens = useCallback(async (access: string, refresh: string) => {
    setSession(access, refresh, {
      id: null, email: "", role: "member", tenant: null, force_password_change: false,
    });
    const fresh = await authApi.me();
    setSession(access, refresh, fresh);
    setUserState(fresh);
    loadPermissions();
    return fresh;
  }, [loadPermissions]);

  const signOut = useCallback(async () => {
    const refresh = getRefresh();
    if (refresh) {
      try {
        await authApi.logout(refresh);
      } catch {
        // best effort
      }
    }
    clearSession();
    setUserState(null);
    setPermissions(new Set());
    if (typeof window !== "undefined") window.location.href = "/login";
  }, []);

  const refreshUser = useCallback(async () => {
    const fresh = await authApi.me();
    setUserState(fresh);
    updateStoredUser(fresh);
    loadPermissions();
  }, [loadPermissions]);

  const setUser = useCallback((u: CurrentUser) => {
    setUserState(u);
    updateStoredUser(u);
  }, []);

  const hasPermission = useCallback(
    (p: Permission | string) =>
      permissions.size > 0 ? permissions.has(p) : roleCan(user, p as Permission),
    [permissions, user],
  );

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, permissions, hasPermission, signIn, completeMfa, establish,
             establishFromTokens, signOut, refreshUser, setUser }),
    [user, loading, permissions, hasPermission, signIn, completeMfa, establish,
     establishFromTokens, signOut, refreshUser, setUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
