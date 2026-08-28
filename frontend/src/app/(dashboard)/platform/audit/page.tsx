"use client";

import { useEffect, useState } from "react";
import { getPlatformAudit } from "@/lib/api/platform";
import type { AuditEntry } from "@/lib/types";
import { Empty, Loading, PageHeader, TableWrap, fmtDate } from "@/components/ui";
import { useToast } from "@/components/Toast";

export default function PlatformAuditPage() {
  const { toast } = useToast();
  const [rows, setRows] = useState<AuditEntry[] | null>(null);

  useEffect(() => {
    getPlatformAudit(200)
      .then(setRows)
      .catch((e) => {
        setRows([]);
        toast(e.message, "error");
      });
  }, [toast]);

  if (!rows) return <Loading />;

  return (
    <>
      <PageHeader title="Platform audit log" subtitle="Every audited event across all workspaces." />
      {rows.length === 0 ? (
        <Empty>No audit entries.</Empty>
      ) : (
        <TableWrap
          head={
            <>
              <th>When</th>
              <th>Workspace</th>
              <th>Actor</th>
              <th>Role</th>
              <th>Action</th>
              <th>Detail</th>
            </>
          }
        >
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="small muted" style={{ whiteSpace: "nowrap" }}>
                {fmtDate(r.created_at)}
              </td>
              <td className="small">{r.tenant_id ?? "—"}</td>
              <td>{r.actor}</td>
              <td className="small muted">{r.role}</td>
              <td>
                <span className="badge">{r.action}</span>
              </td>
              <td className="small muted">{r.detail}</td>
            </tr>
          ))}
        </TableWrap>
      )}
    </>
  );
}
