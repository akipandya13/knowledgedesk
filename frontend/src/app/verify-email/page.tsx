"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { verifyEmail } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";

function Verify() {
  const token = useSearchParams().get("token") || "";
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!token) {
      setState("error");
      setMsg("This link is missing its token.");
      return;
    }
    verifyEmail(token)
      .then(() => setState("ok"))
      .catch((e) => {
        setState("error");
        setMsg(e instanceof ApiError ? e.detail : "Verification failed");
      });
  }, [token]);

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <h1>Email verification</h1>
        {state === "working" && <p className="sub">Verifying…</p>}
        {state === "ok" && <div className="notice green">Your email is verified. You can sign in now.</div>}
        {state === "error" && <div className="notice red">{msg}</div>}
        <div style={{ marginTop: 12, textAlign: "center" }}>
          <Link href="/login" className="small muted">Go to sign in</Link>
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<div className="auth-shell" />}>
      <Verify />
    </Suspense>
  );
}
