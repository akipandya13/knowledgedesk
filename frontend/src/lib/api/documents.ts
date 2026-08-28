"use client";

import { apiFetch } from "./client";
import type { DocumentRow, UploadResult } from "@/lib/types";

export function listDocuments(params?: { status?: string; source?: string }) {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.source) qs.set("source", params.source);
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiFetch<DocumentRow[]>(`/documents${suffix}`);
}

export interface UploadMeta {
  department?: string;
  confidentiality?: string;
  tags?: string;
}

export function uploadDocuments(files: File[], meta: UploadMeta = {}) {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  fd.append("department", meta.department || "");
  fd.append("confidentiality", meta.confidentiality || "internal");
  fd.append("tags", meta.tags || "");
  return apiFetch<UploadResult>("/documents/upload", { method: "POST", body: fd });
}

export function uploadZip(archive: File, meta: UploadMeta = {}) {
  const fd = new FormData();
  fd.append("archive", archive);
  fd.append("department", meta.department || "");
  fd.append("confidentiality", meta.confidentiality || "internal");
  fd.append("tags", meta.tags || "");
  return apiFetch<UploadResult>("/documents/upload-zip", { method: "POST", body: fd });
}

export function deleteDocument(id: number) {
  return apiFetch<{ deleted: number }>(`/documents/${id}`, { method: "DELETE" });
}
