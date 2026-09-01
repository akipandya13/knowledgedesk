"use client";

import { useCallback, useEffect, useState } from "react";
import {
  changePassword,
  listSessions,
  mfaDisable,
  mfaEnable,
  mfaRegenCodes,
  mfaSetup,
  resendVerification,
  revokeAllSessions,
  revokeSession,
} from "@/lib/api/auth";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { AuthSession } from "@/lib/types";
import { Card, Empty, Loading, Notice, PageHeader, TableWrap, fmtDate } from "@/components/ui";
import { IconTrash } from "@/components/icons";
import { useToast } from "@/components/Toast";

export default function SecurityPage() {
  const { toast } = useToast();
  const { user, refreshUser } = useAuth();

  return (
    <>
      <PageHeader title="Security" subtitle="Password, two-factor authentication and active sessions." />
      {user && !user.email_verified && (
        <Notice kind="amber">
          Your email address is not verified.{" "}
          <button className="link-btn" onClick={() =>
            resendVerification().then(() => toast("Verification email sent", "success"))
              .catch((e) => toast(e.message, "error"))}>
            Resend verification email
          </button>
        </Notice>
      )}
      <PasswordCard toast={toast} />
      <MfaCard enabled={!!user?.mfa_enabled} toast={toast} onChange={refreshUser} />
      <SessionsCard toast={toast} />
    </>
  );
}

type Toast = (m: string, k?: "success" | "error" | "warning" | "info") => void;

function PasswordCard({ toast }: { toast: Toast }) {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Card title="Password" style={{ marginBottom: 16 }}>
      <div className="two-col">
        <div className="form-group">
          <label>Current password</label>
          <input type="password" value={cur} onChange={(e) => setCur(e.target.value)} />
        </div>
        <div className="form-group">
          <label>New password</label>
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
        </div>
      </div>
      <button className="btn" disabled={busy || !cur || !next} onClick={async () => {
        setBusy(true);
        try {
          await changePassword(cur, next);
          toast("Password changed — signing out other sessions", "success");
          setCur(""); setNext("");
        } catch (e) {
          toast(e instanceof Error ? e.message : "Failed", "error");
        } finally { setBusy(false); }
      }}>Update password</button>
    </Card>
  );
}

function MfaCard({ enabled, toast, onChange }: { enabled: boolean; toast: Toast; onChange: () => void }) {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [confirmPw, setConfirmPw] = useState("");

  return (
    <Card title="Two-factor authentication (TOTP)" style={{ marginBottom: 16 }}>
      {enabled ? (
        <>
          <Notice kind="green">Two-factor authentication is on.</Notice>
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn secondary" onClick={() =>
              mfaRegenCodes().then((r) => setCodes(r.recovery_codes)).catch((e) => toast(e.message, "error"))}>
              Regenerate recovery codes
            </button>
            <input type="password" placeholder="Password to disable" value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)} style={{ maxWidth: 200 }} />
            <button className="btn danger" onClick={() =>
              mfaDisable({ password: confirmPw }).then(() => { toast("2FA disabled", "success"); onChange(); })
                .catch((e) => toast(e.message, "error"))}>
              Disable
            </button>
          </div>
        </>
      ) : !setup ? (
        <button className="btn" onClick={() =>
          mfaSetup().then(setSetup).catch((e) => toast(e.message, "error"))}>
          Set up two-factor
        </button>
      ) : (
        <>
          <p className="small">
            Add this secret to your authenticator app (Google Authenticator, 1Password, Authy):
          </p>
          <div className="mono" style={{ padding: 8, background: "var(--surface-2, #f4f4f5)", borderRadius: 6, wordBreak: "break-all" }}>
            {setup.secret}
          </div>
          <div className="small muted" style={{ margin: "6px 0" }}>
            or open: <a href={setup.otpauth_uri}>{setup.otpauth_uri}</a>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <input placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} style={{ maxWidth: 160 }} />
            <button className="btn" onClick={() =>
              mfaEnable(code.trim()).then((r) => {
                setCodes(r.recovery_codes); setSetup(null); setCode(""); onChange();
                toast("Two-factor enabled", "success");
              }).catch((e) => toast(e.message, "error"))}>
              Enable
            </button>
          </div>
        </>
      )}

      {codes && (
        <Notice kind="amber">
          <strong>Recovery codes — saved only once.</strong> Store them somewhere safe; each works once.
          <div className="mono" style={{ marginTop: 6, columns: 2 }}>
            {codes.map((c) => <div key={c}>{c}</div>)}
          </div>
        </Notice>
      )}
    </Card>
  );
}

function SessionsCard({ toast }: { toast: Toast }) {
  const [rows, setRows] = useState<AuthSession[] | null>(null);
  const load = useCallback(() =>
    listSessions().then(setRows).catch((e) => toast(e.message, "error")), [toast]);
  useEffect(() => { load(); }, [load]);

  if (!rows) return <Loading />;
  return (
    <Card title="Active sessions">
      {rows.length === 0 ? (
        <Empty>No active sessions.</Empty>
      ) : (
        <TableWrap head={<><th>Device</th><th>IP</th><th>Started</th><th>Last used</th><th /></>}>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="small">{r.label || r.user_agent || "unknown"}</td>
              <td className="small mono">{r.ip || "—"}</td>
              <td className="small muted">{fmtDate(r.created_at)}</td>
              <td className="small muted">{fmtDate(r.last_used_at)}</td>
              <td>
                <button className="btn danger sm" aria-label="Revoke"
                  onClick={() => revokeSession(r.id).then(load).catch((e) => toast(e.message, "error"))}>
                  <IconTrash />
                </button>
              </td>
            </tr>
          ))}
        </TableWrap>
      )}
      <button className="btn ghost" style={{ marginTop: 10 }} onClick={() =>
        revokeAllSessions().then(() => { toast("All sessions ended", "success"); window.location.href = "/login"; })
          .catch((e) => toast(e.message, "error"))}>
        Sign out everywhere
      </button>
    </Card>
  );
}
