"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { changePassword } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/AuthProvider";
import { clearSession } from "@/lib/auth/tokenStore";

export default function ChangePasswordPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const forced = !!user?.force_password_change;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (next !== confirm) {
      setError("New passwords do not match");
      return;
    }
    setBusy(true);
    try {
      await changePassword(current, next);
      // Backend revokes all sessions — force a fresh login.
      setDone(true);
      clearSession();
      setTimeout(() => (window.location.href = "/login"), 1500);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not change password");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1>Change password</h1>
        <p className="sub">
          {forced
            ? "Set a new password to finish signing in."
            : "Update your account password. All sessions will be signed out."}
        </p>

        {done ? (
          <div className="notice green">Password updated. Redirecting to sign in…</div>
        ) : (
          <>
            <div className="form-group">
              <label>Current password</label>
              <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
            </div>
            <div className="form-group">
              <label>New password</label>
              <input type="password" value={next} onChange={(e) => setNext(e.target.value)} required />
              <div className="hint">At least 10 characters, not similar to your email.</div>
            </div>
            <div className="form-group">
              <label>Confirm new password</label>
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
            </div>

            {error && <div className="notice red">{error}</div>}

            <div className="row" style={{ justifyContent: "space-between" }}>
              {!forced && (
                <button type="button" className="btn ghost" onClick={() => router.back()}>
                  Cancel
                </button>
              )}
              <button className="btn" disabled={busy} type="submit">
                {busy ? "Saving…" : "Update password"}
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}
