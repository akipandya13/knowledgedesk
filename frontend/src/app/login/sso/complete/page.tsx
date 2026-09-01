"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { ROLE_HOME } from "@/lib/config";

export default function SsoCompletePage() {
  const { establishFromTokens } = useAuth();
  const [error, setError] = useState("");

  useEffect(() => {
    const hash = typeof window !== "undefined" ? window.location.hash.slice(1) : "";
    const p = new URLSearchParams(hash);
    const access = p.get("access");
    const refresh = p.get("refresh");
    if (!access || !refresh) {
      setError("SSO response was incomplete.");
      return;
    }
    // Drop the tokens from the URL immediately.
    window.history.replaceState(null, "", "/login/sso/complete");
    establishFromTokens(access, refresh)
      .then((u) => {
        window.location.href = u.force_password_change
          ? "/change-password"
          : ROLE_HOME[u.role] || "/ask";
      })
      .catch(() => setError("Could not establish the session."));
  }, [establishFromTokens]);

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <h1>Signing you in…</h1>
        {error ? (
          <div className="notice red">{error} <a href="/login">Back to sign in</a></div>
        ) : (
          <p className="sub">One moment.</p>
        )}
      </div>
    </div>
  );
}
