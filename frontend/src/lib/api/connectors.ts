"use client";

import { apiFetch } from "./client";
import type { ConnectorStatus } from "@/lib/types";

export function getConnectorStatus() {
  return apiFetch<ConnectorStatus>("/connectors/status");
}

export function syncConnector(kind: "gdrive" | "sharepoint") {
  return apiFetch<{ queued: number; source: string }>(`/connectors/${kind}/sync`, {
    method: "POST",
  });
}
