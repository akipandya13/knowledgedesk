"use client";

import { useCallback, useEffect, useState } from "react";
import {
  downloadLogCsv,
  getAuditHistory,
  getTenantAudit,
  verifyTenantAudit,
} from "@/lib/api/admin";
import type { AuditEntry, AuditFilter, AuditVerifyResult } from "@/lib/types";
import { Card, Empty, Loading, Notice, PageHeader, TableWrap, fmtDate } from "@/components/ui";
import { useToast } from "@/components/Toast";

const PAGE = 100;

function fmtVal(v: unknown): string {
  if (v === null || v === undefined || v === "") return "∅";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function Changes({ changes }: { changes: AuditEntry["changes"] }) {
  if (!changes || Object.keys(changes).length === 0) return <span className="muted">—</span>;
  return (
    <div className="small" style={{ display: "grid", gap: 2 }}>
      {Object.entries(changes).map(([field, pair]) => (
        <div key={field}>
          <span className="mono">{field}</span>{" "}
          <span className="muted">{fmtVal(pair?.[0])}</span>
          <span className="muted"> → </span>
          <span>{fmtVal(pair?.[1])}</span>
        </div>
      ))}
    </div>
  );
}

export default function AuditPage() {
  const { toast } = useToast();
  const [rows, setRows] = useState<AuditEntry[] | null>(null);
  const [draft, setDraft] = useState<AuditFilter>({});
  const [filter, setFilter] = useState<AuditFilter>({});
  const [more, setMore] = useState(false);
  const [verify, setVerify] = useState<AuditVerifyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [scope, setScope] = useState<{ type: string; id: string } | null>(null);

  // ?target_type=user&target_id=42 → tamper-evident change timeline for one entity.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const t = p.get("target_type");
    const i = p.get("target_id");
    setScope(t && i ? { type: t, id: i } : null);
  }, []);

  const load = useCallback(
    (f: AuditFilter, append = false) => {
      getTenantAudit({ ...f, limit: PAGE })
        .then((r) => {
          setRows((prev) => (append && prev ? [...prev, ...r] : r));
          setMore(r.length === PAGE);
        })
        .catch((e) => {
          if (!append) setRows([]);
          toast(e.message, "error");
        });
    },
    [toast],
  );

  useEffect(() => {
    if (scope) {
      setMore(false);
      getAuditHistory(scope.type, scope.id)
        .then(setRows)
        .catch((e) => {
          setRows([]);
          toast(e.message, "error");
        });
    } else {
      load(filter);
    }
  }, [filter, load, scope, toast]);

  const runVerify = async () => {
    setBusy(true);
    try {
      setVerify(await verifyTenantAudit());
    } catch (e) {
      toast(e instanceof Error ? e.message : "Verification failed", "error");
    } finally {
      setBusy(false);
    }
  };

  const exportCsv = async () => {
    try {
      await downloadLogCsv("audit", filter);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Export failed", "error");
    }
  };

  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="Tamper-evident record of security-relevant changes in this workspace. Each entry is hash-chained to the one before it."
        actions={
          <div className="row" style={{ gap: 8 }}>
            <button className="btn secondary" disabled={busy} onClick={runVerify}>
              {busy ? "Verifying…" : "Verify integrity"}
            </button>
            <button className="btn secondary" onClick={exportCsv}>
              Export CSV
            </button>
          </div>
        }
      />

      {scope && (
        <Notice kind="info">
          Showing the tamper-evident change history for{" "}
          <span className="mono">{scope.type} #{scope.id}</span>.{" "}
          <a href="/audit" className="link-btn">View the full audit log</a>
        </Notice>
      )}

      {verify && (
        <Notice kind={verify.ok ? "green" : "red"}>
          {verify.ok ? (
            <>
              <strong>Chain intact.</strong> Recomputed {verify.checked} hashed{" "}
              {verify.checked === 1 ? "entry" : "entries"}
              {verify.unchained > 0 && ` (${verify.unchained} pre-upgrade entries are not chained)`}
              {verify.truncated && " · a retention purge has trimmed older entries"}.
            </>
          ) : (
            <>
              <strong>Integrity check failed.</strong>{" "}
              {verify.first_broken
                ? `First bad entry: seq ${verify.first_broken.seq} (#${verify.first_broken.id}) — ${verify.first_broken.reason}.`
                : "The hash chain does not verify."}
            </>
          )}
        </Notice>
      )}

      {!scope && (
      <Card title="Filter" style={{ margin: "14px 0" }}>
        <div className="row" style={{ gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
          <label className="small" style={{ display: "grid", gap: 4 }}>
            Action prefix
            <input
              style={{ width: 180 }}
              placeholder="e.g. auth. or user."
              value={draft.prefix ?? ""}
              onChange={(e) => setDraft({ ...draft, prefix: e.target.value })}
            />
          </label>
          <label className="small" style={{ display: "grid", gap: 4 }}>
            Actor contains
            <input
              style={{ width: 180 }}
              placeholder="email"
              value={draft.actor ?? ""}
              onChange={(e) => setDraft({ ...draft, actor: e.target.value })}
            />
          </label>
          <label className="small" style={{ display: "grid", gap: 4 }}>
            From
            <input
              type="date"
              style={{ width: 160 }}
              value={draft.since ?? ""}
              onChange={(e) => setDraft({ ...draft, since: e.target.value })}
            />
          </label>
          <label className="small" style={{ display: "grid", gap: 4 }}>
            To
            <input
              type="date"
              style={{ width: 160 }}
              value={draft.until ?? ""}
              onChange={(e) => setDraft({ ...draft, until: e.target.value })}
            />
          </label>
          <button
            className="btn"
            onClick={() =>
              setFilter({
                prefix: draft.prefix || undefined,
                actor: draft.actor || undefined,
                since: draft.since ? `${draft.since}T00:00:00` : undefined,
                until: draft.until ? `${draft.until}T23:59:59` : undefined,
              })
            }
          >
            Apply
          </button>
          {(filter.prefix || filter.actor || filter.since || filter.until) && (
            <button
              className="btn secondary"
              onClick={() => {
                setDraft({});
                setFilter({});
              }}
            >
              Clear
            </button>
          )}
        </div>
      </Card>
      )}

      {!rows ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty>No audit entries match.</Empty>
      ) : (
        <>
          <TableWrap
            head={
              <>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Target</th>
                <th>Change</th>
                <th>Detail</th>
              </>
            }
          >
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="small muted" style={{ whiteSpace: "nowrap" }}>
                  {fmtDate(r.created_at)}
                </td>
                <td className="small">
                  {r.actor || "—"}
                  {r.ip && <div className="muted mono" style={{ fontSize: 11 }}>{r.ip}</div>}
                </td>
                <td>
                  <span className="badge">{r.action}</span>
                </td>
                <td className="small mono">
                  {r.target_type ? `${r.target_type}${r.target_id ? ` #${r.target_id}` : ""}` : "—"}
                </td>
                <td><Changes changes={r.changes} /></td>
                <td className="small muted">{r.detail || "—"}</td>
              </tr>
            ))}
          </TableWrap>
          {more && !scope && (
            <div style={{ marginTop: 12 }}>
              <button
                className="btn secondary"
                onClick={() => load({ ...filter, before_id: rows[rows.length - 1].id }, true)}
              >
                Load older
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}
