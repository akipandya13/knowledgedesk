"use client";

import { apiFetch } from "./client";
import type { DocumentRow, SearchScope, UploadResult } from "@/lib/types";

export function listDocuments(params?: {
  status?: string;
  source?: string;
  scope?: SearchScope;
  owner_user_id?: number;
}) {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.source) qs.set("source", params.source);
  if (params?.scope) qs.set("scope", params.scope);
  if (params?.owner_user_id != null) qs.set("owner_user_id", String(params.owner_user_id));
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiFetch<DocumentRow[]>(`/documents${suffix}`);
}

export interface UploadMeta {
  department?: string;
  confidentiality?: string;
  tags?: string;
  /** "" → server default (admins: company-wide, members: own workspace). */
  scope?: "workspace" | "company" | "";
  /** admins only: place the document into this user's workspace. */
  owner_user_id?: number;
}

function appendMeta(fd: FormData, meta: UploadMeta) {
  fd.append("department", meta.department || "");
  fd.append("confidentiality", meta.confidentiality || "internal");
  fd.append("tags", meta.tags || "");
  if (meta.scope) fd.append("scope", meta.scope);
  if (meta.owner_user_id != null) fd.append("owner_user_id", String(meta.owner_user_id));
}

export function uploadDocuments(files: File[], meta: UploadMeta = {}) {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  appendMeta(fd, meta);
  return apiFetch<UploadResult>("/documents/upload", { method: "POST", body: fd });
}

export function uploadZip(archive: File, meta: UploadMeta = {}) {
  const fd = new FormData();
  fd.append("archive", archive);
  appendMeta(fd, meta);
  return apiFetch<UploadResult>("/documents/upload-zip", { method: "POST", body: fd });
}

export function deleteDocument(id: number) {
  return apiFetch<{ deleted: number }>(`/documents/${id}`, { method: "DELETE" });
}
