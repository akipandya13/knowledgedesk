"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  deleteConnector,
  getConnectorProviders,
  getConnectorStatus,
  getSyncRuns,
  listConnectors,
  syncConnector,
  testConnector,
} from "@/lib/api/connectors";
import type {
  ConnectorStatus,
  ConnectorSyncRun,
  DataConnector,
  DataConnectorProviderSpec,
} from "@/lib/types";
import {
  Empty,
  Loading,
  Notice,
  PageHeader,
  StatusBadge,
  TableWrap,
  fmtDate,
} from "@/components/ui";
import { DataConnectorModal } from "@/components/DataConnectorModal";
import { IconTrash } from "@/components/icons";
import { useToast } from "@/components/Toast";

export default function ConnectorsPage() {
  const { toast } = useToast();
  const [providers, setProviders] = useState<Record<string, DataConnectorProviderSpec> | null>(null);
  const [rows, setRows] = useState<DataConnector[] | null>(null);
  const [legacy, setLegacy] = useState<ConnectorStatus | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<DataConnector | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [runs, setRuns] = useState<ConnectorSyncRun[]>([]);
  const [busy, setBusy] = useState<number | null>(null);

  const refresh = useCallback(() => {
    listConnectors()
      .then(setRows)
      .catch((e) => {
        setRows([]);
        toast(e.message, "error");
      });
  }, [toast]);

  useEffect(() => {
    getConnectorProviders().then(setProviders).catch((e) => toast(e.message, "error"));
    getConnectorStatus().then(setLegacy).catch(() => undefined);
    refresh();
  }, [refresh, toast]);

  const anyRunning = useMemo(
    () => (rows || []).some((c) => c.last_sync_status === "running"),
    [rows],
  );

  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(() => {
      refresh();
      if (expanded != null) getSyncRuns(expanded).then(setRuns).catch(() => undefined);
    }, 3000);
    return () => clearInterval(id);
  }, [anyRunning, refresh, expanded]);

  async function onTest(c: DataConnector) {
    setBusy(c.id);
    try {
      const res = await testConnector(c.id);
      toast(res.ok ? `OK — ${res.detail}` : `Failed — ${res.detail}`, res.ok ? "success" : "error");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Test failed", "error");
    } finally {
      setBusy(null);
    }
  }

  async function onSync(c: DataConnector) {
    setBusy(c.id);
    try {
      await syncConnector(c.id);
      toast("Sync started", "success");
      refresh();
      if (expanded === c.id) getSyncRuns(c.id).then(setRuns);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Sync failed", "error");
    } finally {
      setBusy(null);
    }
  }

  async function onDelete(c: DataConnector) {
    if (!confirm(`Delete connector "${c.name}"? Ingested documents are kept.`)) return;
    try {
      await deleteConnector(c.id);
      toast("Connector deleted", "success");
      if (expanded === c.id) setExpanded(null);
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Delete failed", "error");
    }
  }

  function toggleRuns(id: number) {
    if (expanded === id) {
      setExpanded(null);
      return;
    }
    setExpanded(id);
    setRuns([]);
    getSyncRuns(id).then(setRuns).catch(() => undefined);
  }

  if (!providers || !rows) return <Loading />;

  const legacyConfigured =
    legacy && (legacy.gdrive.configured || legacy.sharepoint.configured);

  return (
    <>
      <PageHeader
        title="Data connectors"
        subtitle="Pull documents from Google Drive and SharePoint into this workspace. Credentials are encrypted at rest and never leave the server."
        actions={
          <button
            className="btn"
            onClick={() => {
              setEditing(null);
              setModalOpen(true);
            }}
          >
            + Add connector
          </button>
        }
      />

      {legacyConfigured && (
        <Notice kind="info">
          Legacy <span className="mono">.env</span> connectors are configured
          {legacy?.gdrive.configured ? " (Google Drive)" : ""}
          {legacy?.sharepoint.configured ? " (SharePoint)" : ""}. Prefer the
          per-workspace connectors below.
        </Notice>
      )}

      {rows.length === 0 ? (
        <Empty>No connectors yet. Add one to sync from Google Drive or SharePoint.</Empty>
      ) : (
        <TableWrap
          head={
            <>
              <th>Name</th>
              <th>Provider</th>
              <th>Last sync</th>
              <th>Secrets set</th>
              <th />
            </>
          }
        >
          {rows.map((c) => (
            <Fragment key={c.id}>
              <tr>
                <td style={{ fontWeight: 600 }}>{c.name}</td>
                <td>{providers[c.provider]?.label || c.provider}</td>
                <td>
                  {c.last_sync_status ? (
                    <>
                      <StatusBadge value={c.last_sync_status} />{" "}
                      <span className="small muted">
                        {c.last_sync_at ? fmtDate(c.last_sync_at) : ""}
                      </span>
                      {c.last_sync_detail && (
                        <div className="small muted">{c.last_sync_detail}</div>
                      )}
                    </>
                  ) : (
                    <span className="small muted">never</span>
                  )}
                </td>
                <td className="small muted">
                  {c.secret_fields_set.length ? c.secret_fields_set.join(", ") : "—"}
                </td>
                <td>
                  <div className="row" style={{ gap: 6 }}>
                    <button
                      className="btn ghost sm"
                      disabled={busy === c.id}
                      onClick={() => onTest(c)}
                    >
                      Test
                    </button>
                    <button
                      className="btn sm"
                      disabled={busy === c.id || c.last_sync_status === "running"}
                      onClick={() => onSync(c)}
                    >
                      {c.last_sync_status === "running" ? "Syncing…" : "Sync now"}
                    </button>
                    <button className="btn ghost sm" onClick={() => toggleRuns(c.id)}>
                      {expanded === c.id ? "Hide runs" : "Runs"}
                    </button>
                    <button
                      className="btn ghost sm"
                      onClick={() => {
                        setEditing(c);
                        setModalOpen(true);
                      }}
                    >
                      Edit
                    </button>
                    <button className="btn danger sm" onClick={() => onDelete(c)} aria-label="Delete">
                      <IconTrash />
                    </button>
                  </div>
                </td>
              </tr>
              {expanded === c.id && (
                <tr>
                  <td colSpan={5} style={{ background: "var(--paper)" }}>
                    {runs.length === 0 ? (
                      <div className="small muted">No sync runs yet.</div>
                    ) : (
                      <table>
                        <thead>
                          <tr>
                            <th>Started</th>
                            <th>Status</th>
                            <th>Queued</th>
                            <th>Skipped</th>
                            <th>Failed</th>
                            <th>Detail</th>
                          </tr>
                        </thead>
                        <tbody>
                          {runs.map((r) => (
                            <tr key={r.id}>
                              <td className="small muted">{fmtDate(r.started_at)}</td>
                              <td>
                                <StatusBadge value={r.status} />
                              </td>
                              <td>{r.queued}</td>
                              <td>{r.skipped}</td>
                              <td>{r.failed}</td>
                              <td className="small muted">{r.detail}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </TableWrap>
      )}

      <DataConnectorModal
        open={modalOpen}
        editing={editing}
        providers={providers}
        onClose={() => setModalOpen(false)}
        onSaved={refresh}
      />
    </>
  );
}
