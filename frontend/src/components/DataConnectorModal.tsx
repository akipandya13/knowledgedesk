"use client";

import { useEffect, useState } from "react";
import {
  createConnector,
  testConnector,
  updateConnector,
} from "@/lib/api/connectors";
import type { DataConnector, DataConnectorProviderSpec } from "@/lib/types";
import { Modal } from "./Modal";
import { useToast } from "./Toast";

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  providers: Record<string, DataConnectorProviderSpec>;
  editing: DataConnector | null;
}

export function DataConnectorModal({ open, onClose, onSaved, providers, editing }: Props) {
  const { toast } = useToast();
  const providerKeys = Object.keys(providers);

  const [provider, setProvider] = useState<string>("");
  const [name, setName] = useState("");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; detail: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    setTestResult(null);
    if (editing) {
      setProvider(editing.provider);
      setName(editing.name);
      setConfig({ ...editing.config });
      setSecrets({});
    } else {
      setProvider(providerKeys[0] || "");
      setName("");
      setConfig({});
      setSecrets({});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing]);

  const spec = providers[provider];

  async function save() {
    if (!name.trim()) {
      toast("Name is required", "error");
      return;
    }
    setBusy(true);
    try {
      if (editing) {
        await updateConnector(editing.id, { name: name.trim(), config, secrets });
      } else {
        await createConnector({ name: name.trim(), provider, config, secrets });
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
      setTestResult(await testConnector(editing.id));
    } catch (e) {
      setTestResult({ ok: false, detail: e instanceof Error ? e.message : "Test failed" });
    }
  }

  return (
    <Modal
      open={open}
      wide
      title={editing ? "Edit data connector" : "Add data connector"}
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
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="HR Drive folder" />
      </div>

      <div className="form-group">
        <label>Provider</label>
        <select value={provider} disabled={!!editing} onChange={(e) => setProvider(e.target.value)}>
          {providerKeys.map((k) => (
            <option key={k} value={k}>
              {providers[k].label}
            </option>
          ))}
        </select>
      </div>

      {spec && (
        <>
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
            const ph = isSet ? "•••••••• (leave blank to keep)" : f.placeholder || "";
            return (
              <div className="form-group" key={f.key}>
                <label>
                  {f.label}
                  {f.required ? " *" : ""}
                </label>
                {f.multiline ? (
                  <textarea
                    rows={6}
                    value={secrets[f.key] ?? ""}
                    placeholder={ph}
                    onChange={(e) => setSecrets({ ...secrets, [f.key]: e.target.value })}
                    style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}
                  />
                ) : (
                  <input
                    type="password"
                    value={secrets[f.key] ?? ""}
                    placeholder={ph}
                    onChange={(e) => setSecrets({ ...secrets, [f.key]: e.target.value })}
                  />
                )}
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
