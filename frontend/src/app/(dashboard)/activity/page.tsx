"use client";

import { useCallback, useEffect, useState } from "react";
import { downloadLogCsv, getActivity } from "@/lib/api/admin";
import { listUsers } from "@/lib/api/users";
import type { ActivityEntry, ActivityFilter, UserRow } from "@/lib/types";
import { Card, Empty, Loading, PageHeader, TableWrap, fmtDate } from "@/components/ui";
import { useToast } from "@/components/Toast";

const PAGE = 100;
const CATEGORIES = ["", "read", "write", "auth", "admin", "export"];

export default function ActivityPage() {
  const { toast } = useToast();
  const [rows, setRows] = useState<ActivityEntry[] | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [draft, setDraft] = useState<ActivityFilter>({});
  const [filter, setFilter] = useState<ActivityFilter>({});
  const [more, setMore] = useState(false);

  // Pick up ?user=<id> for a per-person drill-down without pulling in
  // useSearchParams (which would need a Suspense boundary at build time).
  useEffect(() => {
    const uid = new URLSearchParams(window.location.search).get("user");
    if (uid && /^\d+$/.test(uid)) {
      const n = Number(uid);
      setDraft((d) => ({ ...d, user_id: n }));
      setFilter((f) => ({ ...f, user_id: n }));
    }
  }, []);

  useEffect(() => {
    listUsers().then(setUsers).catch(() => undefined);
  }, []);

  const load = useCallback(
    (f: ActivityFilter, append = false) => {
      getActivity({ ...f, limit: PAGE })
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
    load(filter);
  }, [filter, load]);

  const apply = () =>
    setFilter({
      user_id: draft.user_id,
      prefix: draft.prefix || undefined,
      actor: draft.actor || undefined,
      category: draft.category || undefined,
      since: draft.since ? `${draft.since}T00:00:00` : undefined,
      until: draft.until ? `${draft.until}T23:59:59` : undefined,
    });

  const active =
    filter.user_id || filter.prefix || filter.actor || filter.category || filter.since || filter.until;

  return (
    <>
      <PageHeader
        title="User activity"
        subtitle="Who viewed, ran, changed or exported what. The behavioural companion to the audit log — sessions and reads included."
        actions={
          <button
            className="btn secondary"
            onClick={() =>
              downloadLogCsv("activity", filter).catch((e) =>
                toast(e instanceof Error ? e.message : "Export failed", "error"),
              )
            }
          >
            Export CSV
          </button>
        }
      />

      <Card title="Filter" style={{ margin: "14px 0" }}>
        <div className="row" style={{ gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
          <label className="small" style={{ display: "grid", gap: 4 }}>
            User
            <select
              style={{ width: 200 }}
              value={draft.user_id ?? ""}
              onChange={(e) =>
                setDraft({ ...draft, user_id: e.target.value ? Number(e.target.value) : undefined })
              }
            >
              <option value="">Everyone</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.email}
                </option>
              ))}
            </select>
          </label>
          <label className="small" style={{ display: "grid", gap: 4 }}>
            Category
            <select
              style={{ width: 130 }}
              value={draft.category ?? ""}
              onChange={(e) => setDraft({ ...draft, category: e.target.value || undefined })}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c || "any"}
                </option>
              ))}
            </select>
          </label>
          <label className="small" style={{ display: "grid", gap: 4 }}>
            Action prefix
            <input
              style={{ width: 170 }}
              placeholder="e.g. document."
              value={draft.prefix ?? ""}
              onChange={(e) => setDraft({ ...draft, prefix: e.target.value })}
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
          <button className="btn" onClick={apply}>
            Apply
          </button>
          {active ? (
            <button
              className="btn secondary"
              onClick={() => {
                setDraft({});
                setFilter({});
              }}
            >
              Clear
            </button>
          ) : null}
        </div>
      </Card>

      {!rows ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty>No activity matches.</Empty>
      ) : (
        <>
          <TableWrap
            head={
              <>
                <th>When</th>
                <th>User</th>
                <th>Action</th>
                <th>Category</th>
                <th>Target</th>
                <th>Status</th>
                <th>IP</th>
              </>
            }
          >
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="small muted" style={{ whiteSpace: "nowrap" }}>
                  {fmtDate(r.created_at)}
                </td>
                <td className="small">{r.actor || "—"}</td>
                <td className="small mono">{r.action}</td>
                <td className="small">{r.category ? <span className="badge">{r.category}</span> : "—"}</td>
                <td className="small mono">
                  {r.target_type ? `${r.target_type}${r.target_id ? ` #${r.target_id}` : ""}` : "—"}
                </td>
                <td className="small muted">{r.status ?? "—"}</td>
                <td className="small muted mono">{r.ip || "—"}</td>
              </tr>
            ))}
          </TableWrap>
          {more && (
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
