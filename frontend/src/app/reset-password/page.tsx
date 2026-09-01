"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { resetPassword } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

function ResetForm() {
  const token = useSearchParams().get("token") || "";
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (pw !== confirm) return setError("Passwords do not match");
    setBusy(true);
    try {
      await resetPassword(token, pw);
      setDone(true);
      setTimeout(() => (window.location.href = "/login"), 1500);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not reset password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1>Set a new password</h1>
        {!token ? (
          <div className="notice red">This link is missing its token.</div>
        ) : done ? (
          <div className="notice green">Password updated. Redirecting to sign in…</div>
        ) : (
          <>
            <div className="form-group">
              <label>New password</label>
              <input type="password" value={pw} autoFocus onChange={(e) => setPw(e.target.value)} required />
            </div>
            <div className="form-group">
              <label>Confirm new password</label>
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
            </div>
            {error && <div className="notice red">{error}</div>}
            <button className="btn block" disabled={busy} type="submit">
              {busy ? "Saving…" : "Reset password"}
            </button>
          </>
        )}
        <div style={{ marginTop: 12, textAlign: "center" }}>
          <Link href="/login" className="small muted">Back to sign in</Link>
        </div>
      </form>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<div className="auth-shell" />}>
      <ResetForm />
    </Suspense>
  );
}
