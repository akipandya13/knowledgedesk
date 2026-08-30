"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  deleteDocument,
  listDocuments,
  uploadDocuments,
  uploadZip,
  type UploadMeta,
} from "@/lib/api/documents";
import { seedDemo } from "@/lib/api/health";
import { useAuth } from "@/lib/auth/AuthProvider";
import { can } from "@/lib/auth/permissions";
import type { DocumentRow, SearchScope } from "@/lib/types";
import {
  Card,
  Empty,
  Loading,
  Notice,
  PageHeader,
  StatusBadge,
  TableWrap,
  fmtBytes,
  fmtDate,
} from "@/components/ui";
import { IconTrash } from "@/components/icons";
import { useToast } from "@/components/Toast";

const POLL_MS = 2500;

const SCOPE_TABS: { value: SearchScope; label: string }[] = [
  { value: "all", label: "Everything" },
  { value: "workspace", label: "My workspace" },
  { value: "company", label: "Company-wide" },
];

export default function DocumentsPage() {
  const { toast } = useToast();
  const { user } = useAuth();
  const isAdmin = can(user, "document.write.tenant");

  const [docs, setDocs] = useState<DocumentRow[] | null>(null);
  const [tab, setTab] = useState<SearchScope>("all");
  const [meta, setMeta] = useState<UploadMeta>({ confidentiality: "internal", department: "", tags: "" });
  // Where uploads land. Members can only use their own workspace.
  const [uploadScope, setUploadScope] = useState<"company" | "workspace">(
    isAdmin ? "company" : "workspace",
  );
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const zipRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    listDocuments({ scope: tab })
      .then(setDocs)
      .catch((e) => {
        setDocs([]);
        toast(e.message, "error");
      });
  }, [toast, tab]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll while anything is still processing.
  useEffect(() => {
    if (!docs) return;
    const pending = docs.some((d) => d.status === "queued" || d.status === "processing");
    if (!pending) return;
    const id = setTimeout(refresh, POLL_MS);
    return () => clearTimeout(id);
  }, [docs, refresh]);

  const effectiveMeta = useMemo<UploadMeta>(
    () => ({ ...meta, scope: isAdmin ? uploadScope : "workspace" }),
    [meta, isAdmin, uploadScope],
  );

  async function onFiles(files: FileList | null, isZip: boolean) {
    if (!files || files.length === 0) return;
    setUploading(true);
    try {
      const res = isZip
        ? await uploadZip(files[0], effectiveMeta)
        : await uploadDocuments(Array.from(files), effectiveMeta);
      const ok = res.accepted.length;
      const bad = res.rejected.length;
      toast(
        `${ok} document(s) queued${bad ? `, ${bad} rejected` : ""}`,
        bad && !ok ? "warning" : "success",
      );
      if (bad) res.rejected.forEach((r) => toast(`${r.filename}: ${r.reason}`, "warning"));
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Upload failed", "error");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
      if (zipRef.current) zipRef.current.value = "";
    }
  }

  async function onDelete(id: number) {
    if (!confirm("Delete this document and its vectors?")) return;
    try {
      await deleteDocument(id);
      toast("Document deleted", "success");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Delete failed", "error");
    }
  }

  async function onSeed() {
    try {
      const r = await seedDemo();
      toast(r.note || `${r.queued} sample document(s) queued`, r.note ? "warning" : "success");
      setTimeout(refresh, 1200);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Seed failed", "error");
    }
  }

  const canDelete = (d: DocumentRow) =>
    isAdmin || (d.scope === "workspace" && d.owner_user_id === user?.id);

  return (
    <>
      <PageHeader
        title="Documents"
        subtitle={
          isAdmin
            ? "Company-wide documents are searchable by everyone in the workspace. Personal documents stay private to their owner."
            : "Documents you upload here stay private to your workspace. Company-wide documents are published by an admin."
        }
        actions={
          isAdmin ? (
            <button className="btn ghost" onClick={onSeed}>
              Load sample documents
            </button>
          ) : undefined
        }
      />

      <Card title="Upload" style={{ marginBottom: 18 }}>
        <div className="two-col">
          <div className="form-group">
            <label>Department (optional)</label>
            <input
              value={meta.department}
              onChange={(e) => setMeta({ ...meta, department: e.target.value })}
              placeholder="e.g. HR, Engineering"
            />
          </div>
          <div className="form-group">
            <label>Confidentiality</label>
            <select
              value={meta.confidentiality}
              onChange={(e) => setMeta({ ...meta, confidentiality: e.target.value })}
            >
              <option value="public">public</option>
              <option value="internal">internal</option>
              <option value="confidential">confidential</option>
            </select>
          </div>
        </div>
        <div className="two-col">
          <div className="form-group">
            <label>Tags (comma-separated, optional)</label>
            <input
              value={meta.tags}
              onChange={(e) => setMeta({ ...meta, tags: e.target.value })}
              placeholder="policy, 2024, benefits"
            />
          </div>
          <div className="form-group">
            <label>Visibility</label>
            {isAdmin ? (
              <select
                value={uploadScope}
                onChange={(e) => setUploadScope(e.target.value as "company" | "workspace")}
              >
                <option value="company">Company-wide — everyone can search it</option>
                <option value="workspace">My workspace — private to me</option>
              </select>
            ) : (
              <input value="My workspace — private to me" disabled readOnly />
            )}
          </div>
        </div>
        <div className="row">
          <button className="btn" disabled={uploading} onClick={() => fileRef.current?.click()}>
            {uploading ? "Uploading…" : "Select files"}
          </button>
          <button
            className="btn secondary"
            disabled={uploading}
            onClick={() => zipRef.current?.click()}
          >
            Upload ZIP archive
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            hidden
            onChange={(e) => onFiles(e.target.files, false)}
          />
          <input
            ref={zipRef}
            type="file"
            accept=".zip"
            hidden
            onChange={(e) => onFiles(e.target.files, true)}
          />
        </div>
        <div className="hint" style={{ marginTop: 8 }}>
          Supported: PDF, DOCX, PPTX, XLSX, TXT, HTML, MD. Duplicates are skipped by content hash.
        </div>
      </Card>

      <div className="chips" style={{ marginBottom: 12 }}>
        {SCOPE_TABS.map((t) => (
          <button
            key={t.value}
            className={`chip${tab === t.value ? " active" : ""}`}
            onClick={() => setTab(t.value)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {!docs ? (
        <Loading />
      ) : docs.length === 0 ? (
        <Empty>
          {tab === "company"
            ? "No company-wide documents yet."
            : tab === "workspace"
              ? "Nothing in your workspace yet — upload a file above."
              : "No documents yet — upload files or load the sample set."}
        </Empty>
      ) : (
        <>
          {docs.some((d) => d.status === "failed") && (
            <Notice kind="amber">
              Some documents failed to ingest. Hover the status or re-upload after fixing the file.
            </Notice>
          )}
          <TableWrap
            head={
              <>
                <th>File</th>
                <th>Visibility</th>
                <th>Status</th>
                <th>Pages</th>
                <th>Chunks</th>
                <th>Size</th>
                <th>Source</th>
                <th>Added</th>
                <th />
              </>
            }
          >
            {docs.map((d) => (
              <tr key={d.id}>
                <td>
                  <div style={{ fontWeight: 600 }}>{d.filename}</div>
                  {d.department && <span className="badge">{d.department}</span>}{" "}
                  <span className="badge blue">{d.confidentiality}</span>
                  {d.error && <div className="small" style={{ color: "var(--red)" }}>{d.error}</div>}
                </td>
                <td>
                  {d.scope === "tenant" ? (
                    <span className="badge">Company-wide</span>
                  ) : (
                    <span className="badge blue">
                      {d.owner_user_id === user?.id ? "My workspace" : d.owner_email || "Workspace"}
                    </span>
                  )}
                </td>
                <td>
                  <StatusBadge value={d.status} />
                </td>
                <td>{d.pages || "—"}</td>
                <td>{d.chunks || "—"}</td>
                <td>{fmtBytes(d.size_bytes)}</td>
                <td>{d.source}</td>
                <td className="small muted">{fmtDate(d.created_at)}</td>
                <td>
                  {canDelete(d) && (
                    <button className="btn danger sm" onClick={() => onDelete(d.id)} aria-label="Delete">
                      <IconTrash />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </TableWrap>
        </>
      )}
    </>
  );
}
