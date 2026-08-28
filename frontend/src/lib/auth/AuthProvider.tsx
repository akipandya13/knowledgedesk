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
import {
  clearSession,
  getAccess,
  getRefresh,
  getStoredUser,
  setSession,
  updateStoredUser,
} from "./tokenStore";
import type { CurrentUser } from "@/lib/types";

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<CurrentUser>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
  setUser: (u: CurrentUser) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);
AuthContext.displayName = "AuthContext";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = getStoredUser();
    if (stored && getAccess()) {
      setUserState(stored);
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
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const pair = await authApi.login(email, password);
    setSession(pair.access_token, pair.refresh_token, pair.user);
    setUserState(pair.user);
    return pair.user;
  }, []);

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
    if (typeof window !== "undefined") window.location.href = "/login";
  }, []);

  const refreshUser = useCallback(async () => {
    const fresh = await authApi.me();
    setUserState(fresh);
    updateStoredUser(fresh);
  }, []);

  const setUser = useCallback((u: CurrentUser) => {
    setUserState(u);
    updateStoredUser(u);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, signIn, signOut, refreshUser, setUser }),
    [user, loading, signIn, signOut, refreshUser, setUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
