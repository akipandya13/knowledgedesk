"use client";

import { useEffect, useState } from "react";
import { getConnectorStatus, syncConnector } from "@/lib/api/connectors";
import type { ConnectorStatus } from "@/lib/types";
import { Card, Loading, PageHeader } from "@/components/ui";
import { useToast } from "@/components/Toast";

const SOURCES: { key: "gdrive" | "sharepoint"; name: string; env: string; blurb: string }[] = [
  {
    key: "gdrive",
    name: "Google Drive",
    env: "GDRIVE_ACCESS_TOKEN, GDRIVE_FOLDER_ID",
    blurb: "Pull documents from a shared Drive folder.",
  },
  {
    key: "sharepoint",
    name: "SharePoint",
    env: "MSGRAPH_* credentials",
    blurb: "Sync from a SharePoint document library via Microsoft Graph.",
  },
];

export default function ConnectorsPage() {
  const { toast } = useToast();
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [busy, setBusy] = useState<string>("");

  useEffect(() => {
    getConnectorStatus()
      .then(setStatus)
      .catch((e) => toast(e.message, "error"));
  }, [toast]);

  async function sync(kind: "gdrive" | "sharepoint") {
    setBusy(kind);
    try {
      const res = await syncConnector(kind);
      toast(`${res.queued} file(s) queued from ${kind}`, "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Sync failed", "error");
    } finally {
      setBusy("");
    }
  }

  if (!status) return <Loading />;

  return (
    <>
      <PageHeader
        title="Data connectors"
        subtitle="Bulk-ingest documents from external sources. Credentials are configured in the backend .env."
      />
      <div className="two-col">
        {SOURCES.map((s) => {
          const configured = status[s.key].configured;
          return (
            <Card key={s.key} title={s.name}>
              <p className="small muted" style={{ marginBottom: 14 }}>
                {s.blurb}
              </p>
              <div className="row" style={{ marginBottom: 14 }}>
                <span className={`badge ${configured ? "green" : "amber"}`}>
                  {configured ? "configured" : "not configured"}
                </span>
              </div>
              {!configured && (
                <div className="hint" style={{ marginBottom: 12 }}>
                  Set {s.env} in the backend environment to enable this connector.
                </div>
              )}
              <button
                className="btn"
                disabled={!configured || busy === s.key}
                onClick={() => sync(s.key)}
              >
                {busy === s.key ? "Syncing…" : "Sync now"}
              </button>
            </Card>
          );
        })}
      </div>
    </>
  );
}
