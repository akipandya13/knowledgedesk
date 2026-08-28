"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getEffectiveConfig, getModelCatalog, updateSettings } from "@/lib/api/admin";
import { listConnectors } from "@/lib/api/modelConnectors";
import type { EffectiveConfig, ModelCatalog, ModelConnector } from "@/lib/types";
import { Card, Loading, Notice, PageHeader } from "@/components/ui";
import { useToast } from "@/components/Toast";

interface FormState {
  model_profile: string;
  llm_connector_id: string;
  embedding_connector_id: string;
  llm_model: string;
  embedding_model: string;
  reranker_model: string;
  reranker_enabled: boolean;
  retrieval_top_k: number;
  rerank_top_k: number;
  retrieval_score_threshold: number;
  retrieval_max_context_chars: number;
  llm_max_tokens: number;
  llm_temperature: number;
}

export default function SettingsPage() {
  const { toast } = useToast();
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [config, setConfig] = useState<EffectiveConfig | null>(null);
  const [connectors, setConnectors] = useState<ModelConnector[]>([]);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const [cat, cfg, conns] = await Promise.all([
      getModelCatalog(),
      getEffectiveConfig(),
      listConnectors(),
    ]);
    setCatalog(cat);
    setConfig(cfg);
    setConnectors(conns);
    const ov = (cfg.tenant_overrides || {}) as Record<string, unknown>;
    setForm({
      model_profile: cfg.model_profile || "enterprise_balanced",
      llm_connector_id: String(ov.llm_connector_id || ""),
      embedding_connector_id: String(ov.embedding_connector_id || ""),
      llm_model: cfg.llm_model || "",
      embedding_model: cfg.embedding_model || "",
      reranker_model: cfg.reranker_model || "",
      reranker_enabled: !!cfg.reranker_enabled,
      retrieval_top_k: cfg.retrieval_top_k,
      rerank_top_k: cfg.rerank_top_k,
      retrieval_score_threshold: cfg.retrieval_score_threshold,
      retrieval_max_context_chars: cfg.retrieval_max_context_chars,
      llm_max_tokens: cfg.llm_max_tokens,
      llm_temperature: cfg.llm_temperature,
    });
  }, []);

  useEffect(() => {
    load().catch((e) => toast(e instanceof Error ? e.message : "Failed to load settings", "error"));
  }, [load, toast]);

  const llmConnectors = useMemo(() => connectors.filter((c) => c.kind === "llm"), [connectors]);
  const embeddingConnectors = useMemo(
    () => connectors.filter((c) => c.kind === "embedding"),
    [connectors],
  );

  if (!catalog || !config || !form) return <Loading />;

  const locked = config.embedding_locked;
  const usingLlmConnector = !!form.llm_connector_id;
  const usingEmbeddingConnector = !!form.embedding_connector_id;

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
  }

  function applyProfile(key: string) {
    const p = catalog!.profiles.find((x) => x.key === key);
    if (!p) {
      set("model_profile", key);
      return;
    }
    setForm((f) =>
      f
        ? {
            ...f,
            model_profile: key,
            llm_model: p.llm_model,
            embedding_model: locked ? f.embedding_model : p.embedding_model,
            reranker_model: p.reranker_model,
            reranker_enabled: p.reranker_enabled,
            retrieval_top_k: p.retrieval_top_k,
            rerank_top_k: p.rerank_top_k,
            retrieval_score_threshold: p.retrieval_score_threshold,
            retrieval_max_context_chars: p.retrieval_max_context_chars,
            llm_max_tokens: p.llm_max_tokens,
            llm_temperature: p.llm_temperature,
          }
        : f,
    );
  }

  async function save() {
    if (!form) return;
    setSaving(true);
    const settings: Record<string, unknown> = {
      model_profile: form.model_profile,
      reranker_enabled: form.reranker_enabled,
      reranker_model: form.reranker_model,
      rerank_top_k: Number(form.rerank_top_k),
      retrieval_top_k: Number(form.retrieval_top_k),
      retrieval_score_threshold: Number(form.retrieval_score_threshold),
      retrieval_max_context_chars: Number(form.retrieval_max_context_chars),
      llm_max_tokens: Number(form.llm_max_tokens),
      llm_temperature: Number(form.llm_temperature),
      llm_connector_id: form.llm_connector_id || "",
    };
    if (!usingLlmConnector) {
      settings.llm_provider = form.llm_model === "none" ? "none" : "ollama";
      settings.llm_model = form.llm_model;
    }
    if (!locked) {
      settings.embedding_connector_id = form.embedding_connector_id || "";
      if (!usingEmbeddingConnector) {
        settings.embedding_provider = "local";
        settings.embedding_model = form.embedding_model;
      }
    }

    try {
      const res = await updateSettings(settings);
      toast(res.note || "Settings saved", res.note ? "warning" : "success");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Save failed", "error");
    } finally {
      setSaving(false);
    }
  }

  const idx = config.index_status;

  return (
    <>
      <PageHeader
        title="Workspace settings"
        subtitle="Choose the generation and embedding backends, retrieval tuning and answer behaviour for this workspace."
      />

      <div className="two-col">
        <Card title="Models">
          <div className="form-group">
            <label>Quality / cost profile</label>
            <select value={form.model_profile} onChange={(e) => applyProfile(e.target.value)}>
              {catalog.profiles.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </select>
            <div className="hint">
              {catalog.profiles.find((p) => p.key === form.model_profile)?.description}
            </div>
          </div>

          <div className="form-group">
            <label>LLM connector</label>
            <select
              value={form.llm_connector_id}
              onChange={(e) => set("llm_connector_id", e.target.value)}
            >
              <option value="">Built-in local model</option>
              {llmConnectors.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name} — {catalog.connector_providers[c.provider]?.label || c.provider} ({c.model_id})
                </option>
              ))}
            </select>
            <div className="hint">
              Manage backends on the <a href="/model-connectors">Model connectors</a> page.
            </div>
          </div>

          {!usingLlmConnector && (
            <div className="form-group">
              <label>Built-in generation model</label>
              <select value={form.llm_model} onChange={(e) => set("llm_model", e.target.value)}>
                {catalog.llm_models.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="form-group">
            <label>Embedding connector</label>
            <select
              value={form.embedding_connector_id}
              disabled={locked}
              onChange={(e) => set("embedding_connector_id", e.target.value)}
            >
              <option value="">Built-in local model</option>
              {embeddingConnectors.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name} — {catalog.connector_providers[c.provider]?.label || c.provider} ({c.model_id})
                </option>
              ))}
            </select>
          </div>

          {!usingEmbeddingConnector && (
            <div className="form-group">
              <label>Built-in embedding model</label>
              <select
                value={form.embedding_model}
                disabled={locked}
                onChange={(e) => set("embedding_model", e.target.value)}
              >
                {catalog.embedding_models.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {locked && (
            <Notice kind="amber">
              🔒 {config.embedding_locked_reason || "Embedding model is locked."} Current:{" "}
              {config.embedding_connector ? config.embedding_connector.name : config.embedding_model || "built-in"}.
            </Notice>
          )}

          <div className="form-group">
            <label>Reranker model</label>
            <select value={form.reranker_model} onChange={(e) => set("reranker_model", e.target.value)}>
              {catalog.reranker_models.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group row" style={{ gap: 8 }}>
            <input
              id="rr"
              type="checkbox"
              style={{ width: "auto" }}
              checked={form.reranker_enabled}
              onChange={(e) => set("reranker_enabled", e.target.checked)}
            />
            <label htmlFor="rr" style={{ margin: 0 }}>
              Enable reranker
            </label>
          </div>

          {idx.reindex_required && (
            <Notice kind="amber">
              {idx.documents_indexed_for_current_embedding}/{idx.ready_documents} ready documents are indexed
              for {idx.current_embedding_model}. Re-upload documents after changing the embedding model.
            </Notice>
          )}

          <button className="btn" disabled={saving} onClick={save}>
            {saving ? "Saving…" : "Save settings"}
          </button>
        </Card>

        <div className="stack">
          <Card title="Retrieval tuning">
            <NumberField label="Retrieval pool Top-K" value={form.retrieval_top_k} onChange={(v) => set("retrieval_top_k", v)} min={1} max={80} />
            <NumberField label="Final reranked chunks" value={form.rerank_top_k} onChange={(v) => set("rerank_top_k", v)} min={1} max={20} />
            <NumberField label="Score threshold (0–1)" value={form.retrieval_score_threshold} onChange={(v) => set("retrieval_score_threshold", v)} step={0.01} min={0} max={1} />
            <NumberField label="Max context characters" value={form.retrieval_max_context_chars} onChange={(v) => set("retrieval_max_context_chars", v)} min={2000} max={64000} step={500} />
            <NumberField label="LLM max tokens" value={form.llm_max_tokens} onChange={(v) => set("llm_max_tokens", v)} min={64} max={4000} step={10} />
            <NumberField label="Temperature" value={form.llm_temperature} onChange={(v) => set("llm_temperature", v)} step={0.05} min={0} max={1} />
          </Card>

          <Card title="Effective configuration">
            <div className="mono small" style={{ lineHeight: 1.9 }}>
              <div><b>profile</b>: {config.model_profile}</div>
              <div><b>llm</b>: {config.llm_connector ? `${config.llm_connector.name} (${config.llm_connector.provider}:${config.llm_connector.model_id})` : `${config.llm_provider}:${config.llm_model}`}</div>
              <div><b>embedding</b>: {config.embedding_connector ? `${config.embedding_connector.name} (${config.embedding_connector.provider}:${config.embedding_connector.model_id})` : `${config.embedding_provider}:${config.embedding_model}`}</div>
              <div><b>embedding_locked</b>: {String(config.embedding_locked)}</div>
              <div><b>reranker</b>: {config.reranker_enabled ? config.reranker_model || "on" : "off"}</div>
              <div><b>top_k / rerank_k</b>: {config.retrieval_top_k} / {config.rerank_top_k}</div>
              <div><b>threshold</b>: {config.retrieval_score_threshold}</div>
              <div><b>context_chars</b>: {config.retrieval_max_context_chars}</div>
              <div><b>chunk</b>: {config.chunk_size}/{config.chunk_overlap}</div>
              <div><b>ready docs</b>: {idx.ready_documents} ({idx.documents_indexed_for_current_embedding} on current embedding)</div>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <div className="form-group">
      <label>{label}</label>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step ?? 1}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}
