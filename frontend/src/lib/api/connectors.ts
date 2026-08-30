"use client";

import { apiFetch } from "./client";
import type {
  ConnectorStatus,
  ConnectorSyncRun,
  ConnectorTestResult,
  DataConnector,
  DataConnectorProviderSpec,
} from "@/lib/types";

export function getConnectorStatus() {
  return apiFetch<ConnectorStatus>("/connectors/status");
}

export function getConnectorProviders() {
  return apiFetch<Record<string, DataConnectorProviderSpec>>("/connectors/providers");
}

export function listConnectors() {
  return apiFetch<DataConnector[]>("/connectors");
}

export interface DataConnectorCreate {
  name: string;
  provider: string;
  config: Record<string, string>;
  secrets: Record<string, string>;
}

export interface DataConnectorUpdate {
  name?: string;
  config?: Record<string, string>;
  secrets?: Record<string, string>;
  is_active?: boolean;
}

export function createConnector(body: DataConnectorCreate) {
  return apiFetch<DataConnector>("/connectors", { method: "POST", body });
}

export function updateConnector(id: number, body: DataConnectorUpdate) {
  return apiFetch<DataConnector>(`/connectors/${id}`, { method: "PUT", body });
}

export function deleteConnector(id: number) {
  return apiFetch<{ deleted: number }>(`/connectors/${id}`, { method: "DELETE" });
}

export function testConnector(id: number) {
  return apiFetch<ConnectorTestResult>(`/connectors/${id}/test`, { method: "POST" });
}

export function syncConnector(id: number) {
  return apiFetch<{ run_id: number; status: string }>(`/connectors/${id}/sync`, {
    method: "POST",
  });
}

export function getSyncRuns(id: number, limit = 20) {
  return apiFetch<ConnectorSyncRun[]>(`/connectors/${id}/runs?limit=${limit}`);
}
