"use client";

import { useEffect, useMemo, useState } from "react";
import {
  createConnector,
  testConnector,
  updateConnector,
} from "@/lib/api/modelConnectors";
import type { ConnectorKind, ModelCatalog, ModelConnector } from "@/lib/types";
import { Modal } from "./Modal";
import { useToast } from "./Toast";

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  catalog: ModelCatalog;
  editing: ModelConnector | null;
}

export function ConnectorModal({ open, onClose, onSaved, catalog, editing }: Props) {
  const { toast } = useToast();
  const providers = catalog.connector_providers;

  const [kind, setKind] = useState<ConnectorKind>("llm");
  const [provider, setProvider] = useState<string>("");
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; detail: string } | null>(null);

  const providerKeysForKind = useMemo(
    () => Object.entries(providers).filter(([, spec]) => spec.kinds.includes(kind)).map(([k]) => k),
    [providers, kind],
  );

  useEffect(() => {
    if (!open) return;
    setTestResult(null);
    if (editing) {
      setKind(editing.kind);
      setProvider(editing.provider);
      setName(editing.name);
      setModelId(editing.model_id);
      setConfig({ ...editing.config });
      setSecrets({});
    } else {
      setKind("llm");
      setProvider("");
      setName("");
      setModelId("");
      setConfig({});
      setSecrets({});
    }
  }, [open, editing]);

  // Keep provider valid for the selected kind.
  useEffect(() => {
    if (!open || editing) return;
    if (!providerKeysForKind.includes(provider)) {
      setProvider(providerKeysForKind[0] || "");
    }
  }, [open, editing, kind, provider, providerKeysForKind]);

  const spec = providers[provider];

  async function save() {
    if (!name.trim()) {
      toast("Name is required", "error");
      return;
    }
    setBusy(true);
    try {
      if (editing) {
        await updateConnector(editing.id, {
          name: name.trim(),
          model_id: modelId.trim(),
          config,
          secrets,
        });
      } else {
        await createConnector({
          kind,
          name: name.trim(),
          provider,
          model_id: modelId.trim(),
          config,
          secrets,
        });
      }
      toast("Connector saved", "success");
      onSaved();
      onClose();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Save failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    if (!editing) return;
    setTestResult({ ok: false, detail: "Testing…" });
    try {
      const res = await testConnector(editing.id);
      setTestResult(res);
    } catch (e) {
      setTestResult({ ok: false, detail: e instanceof Error ? e.message : "Test failed" });
    }
  }

  return (
    <Modal
      open={open}
      wide
      title={editing ? "Edit model connector" : "Add model connector"}
      onClose={onClose}
      footer={
        <>
          <button className="btn secondary" onClick={onClose}>
            Cancel
          </button>
          {editing && (
            <button className="btn ghost" onClick={runTest}>
              Test
            </button>
          )}
          <button className="btn" disabled={busy} onClick={save}>
            {busy ? "Saving…" : "Save connector"}
          </button>
        </>
      }
    >
      <div className="form-group">
        <label>Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Bedrock Claude (prod)" />
      </div>

      <div className="two-col">
        <div className="form-group">
          <label>Purpose</label>
          <select
            value={kind}
            disabled={!!editing}
            onChange={(e) => setKind(e.target.value as ConnectorKind)}
          >
            <option value="llm">LLM — answer generation</option>
            <option value="embedding">Embedding — document / query vectors</option>
          </select>
        </div>
        <div className="form-group">
          <label>Provider</label>
          <select
            value={provider}
            disabled={!!editing}
            onChange={(e) => setProvider(e.target.value)}
          >
            {providerKeysForKind.map((k) => (
              <option key={k} value={k}>
                {providers[k].label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {spec && (
        <>
          <div className="form-group">
            <label>Model ID</label>
            <input value={modelId} onChange={(e) => setModelId(e.target.value)} />
            {spec.model_id_hint && <div className="hint">{spec.model_id_hint}</div>}
          </div>

          {spec.config_fields.map((f) => (
            <div className="form-group" key={f.key}>
              <label>
                {f.label}
                {f.required ? " *" : ""}
              </label>
              <input
                value={config[f.key] ?? ""}
                placeholder={f.placeholder || ""}
                onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })}
              />
            </div>
          ))}

          {spec.secret_fields.map((f) => {
            const isSet = editing?.secret_fields_set.includes(f.key);
            return (
              <div className="form-group" key={f.key}>
                <label>
                  {f.label}
                  {f.required ? " *" : ""}
                </label>
                <input
                  type="password"
                  value={secrets[f.key] ?? ""}
                  placeholder={isSet ? "•••••••• (leave blank to keep)" : ""}
                  onChange={(e) => setSecrets({ ...secrets, [f.key]: e.target.value })}
                />
              </div>
            );
          })}

          {spec.secret_note && <div className="hint">{spec.secret_note}</div>}
          <div className="hint">Tip: any secret field may be a store reference &mdash; <span className="mono">{"${env:NAME}"}</span>, <span className="mono">{"${file:/run/secrets/x}"}</span> or <span className="mono">{"${vault:path#key}"}</span> &mdash; instead of the literal value.</div>
        </>
      )}

      {testResult && (
        <div className={`notice ${testResult.ok ? "green" : "amber"}`} style={{ marginTop: 12 }}>
          {testResult.ok ? "OK — " : "Failed — "}
          {testResult.detail}
        </div>
      )}
    </Modal>
  );
}
