"use client";

import { apiFetch } from "./client";
import type { ConnectorKind, ConnectorTestResult, ModelConnector } from "@/lib/types";

export interface ConnectorCreate {
  kind: ConnectorKind;
  name: string;
  provider: string;
  model_id: string;
  config: Record<string, string>;
  secrets: Record<string, string>;
}

export interface ConnectorUpdate {
  name?: string;
  model_id?: string;
  config?: Record<string, string>;
  secrets?: Record<string, string>;
  is_active?: boolean;
}

export function listConnectors() {
  return apiFetch<ModelConnector[]>("/admin/model-connectors");
}

export function createConnector(body: ConnectorCreate) {
  return apiFetch<ModelConnector>("/admin/model-connectors", { method: "POST", body });
}

export function updateConnector(id: number, body: ConnectorUpdate) {
  return apiFetch<ModelConnector>(`/admin/model-connectors/${id}`, { method: "PUT", body });
}

export function deleteConnector(id: number) {
  return apiFetch<{ deleted: number }>(`/admin/model-connectors/${id}`, { method: "DELETE" });
}

export function testConnector(id: number) {
  return apiFetch<ConnectorTestResult>(`/admin/model-connectors/${id}/test`, { method: "POST" });
}
