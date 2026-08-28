"use client";

import { useCallback, useEffect, useState } from "react";
import { getModelCatalog } from "@/lib/api/admin";
import { deleteConnector, listConnectors, testConnector } from "@/lib/api/modelConnectors";
import type { ModelCatalog, ModelConnector } from "@/lib/types";
import { Empty, Loading, Notice, PageHeader, TableWrap } from "@/components/ui";
import { ConnectorModal } from "@/components/ConnectorModal";
import { IconTrash } from "@/components/icons";
import { useToast } from "@/components/Toast";

export default function ModelConnectorsPage() {
  const { toast } = useToast();
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [rows, setRows] = useState<ModelConnector[] | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ModelConnector | null>(null);

  const refresh = useCallback(() => {
    listConnectors()
      .then(setRows)
      .catch((e) => {
        setRows([]);
        toast(e.message, "error");
      });
  }, [toast]);

  useEffect(() => {
    getModelCatalog()
      .then(setCatalog)
      .catch((e) => toast(e.message, "error"));
    refresh();
  }, [refresh, toast]);

  async function runTest(c: ModelConnector) {
    toast("Testing connector…", "info");
    try {
      const res = await testConnector(c.id);
      toast(res.ok ? `OK — ${res.detail}` : `Failed — ${res.detail}`, res.ok ? "success" : "error");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Test failed", "error");
    }
  }

  async function onDelete(c: ModelConnector) {
    if (!confirm(`Delete connector "${c.name}"?`)) return;
    try {
      await deleteConnector(c.id);
      toast("Connector deleted", "success");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Delete failed", "error");
    }
  }

  if (!catalog || !rows) return <Loading />;

  return (
    <>
      <PageHeader
        title="Model connectors"
        subtitle="Define the LLM and embedding backends for this workspace — AWS Bedrock, Azure AI Foundry, or a local model. Pick the active ones on the Settings page."
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

      <Notice kind="info">
        Credentials are encrypted at rest with the backend&apos;s <span className="mono">KD_SECRET_KEY</span> and
        are never returned by the API — only which secret fields are set.
      </Notice>

      {rows.length === 0 ? (
        <Empty>No connectors yet. Add one to use Bedrock, Azure AI Foundry, or a local model.</Empty>
      ) : (
        <TableWrap
          head={
            <>
              <th>Name</th>
              <th>Type</th>
              <th>Provider</th>
              <th>Model</th>
              <th>Secrets set</th>
              <th />
            </>
          }
        >
          {rows.map((c) => (
            <tr key={c.id}>
              <td style={{ fontWeight: 600 }}>{c.name}</td>
              <td>
                <span className="badge blue">{c.kind === "llm" ? "LLM" : "Embedding"}</span>
              </td>
              <td>{catalog.connector_providers[c.provider]?.label || c.provider}</td>
              <td className="mono">{c.model_id || "—"}</td>
              <td className="small muted">
                {c.secret_fields_set.length ? c.secret_fields_set.join(", ") : "—"}
              </td>
              <td>
                <div className="row" style={{ gap: 6 }}>
                  <button className="btn ghost sm" onClick={() => runTest(c)}>
                    Test
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
          ))}
        </TableWrap>
      )}

      <ConnectorModal
        open={modalOpen}
        editing={editing}
        catalog={catalog}
        onClose={() => setModalOpen(false)}
        onSaved={refresh}
      />
    </>
  );
}
