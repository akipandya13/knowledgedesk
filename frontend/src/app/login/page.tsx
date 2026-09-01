"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { ssoLookup } from "@/lib/api/auth";
import { ROLE_HOME } from "@/lib/config";
import { ApiError } from "@/lib/api/client";
import type { CurrentUser } from "@/lib/types";

const SSO_ERRORS: Record<string, string> = {
  cancelled: "SSO sign-in was cancelled.",
  bad_state: "SSO session expired — try again.",
  expired: "SSO session expired — try again.",
  unavailable: "SSO is not available for this workspace.",
  verify_failed: "Could not verify the identity provider response.",
  no_verified_email: "Your identity provider did not return a verified email.",
  domain_not_allowed: "Your email domain is not allowed for this workspace.",
  account_in_another_workspace: "That account belongs to a different workspace.",
  account_disabled: "That account is disabled.",
};

function LoginForm() {
  const { user, loading, signIn, completeMfa } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next");
  const ssoError = params.get("sso_error");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [sso, setSso] = useState<{ display_name: string; start_url: string } | null>(null);

  useEffect(() => {
    if (!loading && user) {
      router.replace(user.force_password_change ? "/change-password" : ROLE_HOME[user.role] || "/ask");
    }
  }, [user, loading, router]);

  useEffect(() => {
    if (ssoError) setError(SSO_ERRORS[ssoError] || "SSO sign-in failed.");
  }, [ssoError]);

  const finish = (u: CurrentUser) =>
    router.replace(u.force_password_change ? "/change-password" : next || ROLE_HOME[u.role] || "/ask");

  async function checkSso() {
    if (!email.includes("@")) return;
    try {
      const r = await ssoLookup(email.trim().toLowerCase());
      setSso(r.available && r.start_url ? { display_name: r.display_name || "SSO", start_url: r.start_url } : null);
    } catch {
      setSso(null);
    }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await signIn(email.trim().toLowerCase(), password.trim());
      if (res.kind === "mfa") setMfaToken(res.mfaToken);
      else finish(res.user);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  const submitMfa = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      finish(await completeMfa(mfaToken!, code.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Invalid code");
    } finally {
      setBusy(false);
    }
  };

  if (mfaToken) {
    return (
      <div className="auth-shell">
        <form className="auth-card" onSubmit={submitMfa}>
          <h1>Two-factor</h1>
          <p className="sub">Enter the 6-digit code from your authenticator app, or a recovery code.</p>
          <div className="form-group">
            <label htmlFor="code">Authentication code</label>
            <input id="code" autoFocus autoComplete="one-time-code" value={code}
              onChange={(e) => setCode(e.target.value)} required />
          </div>
          {error && <div className="notice red">{error}</div>}
          <button className="btn block" disabled={busy} type="submit">
            {busy ? "Verifying…" : "Verify"}
          </button>
          <button type="button" className="link-btn" style={{ marginTop: 10 }}
            onClick={() => { setMfaToken(null); setCode(""); setError(""); }}>
            ← Back
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1>KnowledgeDesk</h1>
        <p className="sub">Sign in to your workspace.</p>

        <div className="form-group">
          <label htmlFor="email">Work email</label>
          <input id="email" type="email" autoComplete="username" value={email}
            onChange={(e) => setEmail(e.target.value)} onBlur={checkSso} required />
        </div>
        <div className="form-group">
          <label htmlFor="password">Password</label>
          <input id="password" type="password" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
        </div>

        {error && <div className="notice red">{error}</div>}

        <button className="btn block" disabled={busy} type="submit">
          {busy ? "Signing in…" : "Sign in"}
        </button>

        {sso && (
          <a className="btn block secondary" href={sso.start_url} style={{ marginTop: 8, textAlign: "center" }}>
            Sign in with {sso.display_name}
          </a>
        )}

        <div style={{ marginTop: 12, textAlign: "center" }}>
          <Link href="/forgot-password" className="small muted">Forgot password?</Link>
        </div>
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
