"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { ROLE_HOME } from "@/lib/config";
import { ApiError } from "@/lib/api/client";

function LoginForm() {
  const { user, loading, signIn } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) {
      router.replace(user.force_password_change ? "/change-password" : ROLE_HOME[user.role] || "/ask");
    }
  }, [user, loading, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const u = await signIn(email.trim().toLowerCase(), password);
      if (u.force_password_change) router.replace("/change-password");
      else router.replace(next || ROLE_HOME[u.role] || "/ask");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1>KnowledgeDesk</h1>
        <p className="sub">Sign in to your workspace.</p>

        <div className="form-group">
          <label htmlFor="email">Work email</label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>
        <div className="form-group">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>

        {error && <div className="notice red">{error}</div>}

        <button className="btn block" disabled={busy} type="submit">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="auth-shell" />}>
      <LoginForm />
    </Suspense>
  );
}
