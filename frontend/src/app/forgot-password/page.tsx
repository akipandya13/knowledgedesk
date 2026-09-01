"use client";

import { useState } from "react";
import Link from "next/link";
import { forgotPassword } from "@/lib/api/auth";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await forgotPassword(email.trim().toLowerCase());
    } finally {
      setSent(true);
      setBusy(false);
    }
  };

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1>Reset password</h1>
        {sent ? (
          <>
            <div className="notice green">
              If an account exists for that address, a reset link is on its way.
            </div>
            <div style={{ marginTop: 12, textAlign: "center" }}>
              <Link href="/login" className="small muted">Back to sign in</Link>
            </div>
          </>
        ) : (
          <>
            <p className="sub">Enter your work email and we&apos;ll send a reset link.</p>
            <div className="form-group">
              <label htmlFor="email">Work email</label>
              <input id="email" type="email" value={email} autoFocus
                onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <button className="btn block" disabled={busy} type="submit">
              {busy ? "Sending…" : "Send reset link"}
            </button>
            <div style={{ marginTop: 12, textAlign: "center" }}>
              <Link href="/login" className="small muted">Back to sign in</Link>
            </div>
          </>
        )}
      </form>
    </div>
  );
}
