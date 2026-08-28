"use client";

import { useEffect, useState } from "react";
import { getTenantAudit } from "@/lib/api/admin";
import type { AuditEntry } from "@/lib/types";
import { Empty, Loading, PageHeader, TableWrap, fmtDate } from "@/components/ui";
import { useToast } from "@/components/Toast";

export default function AuditPage() {
  const { toast } = useToast();
  const [rows, setRows] = useState<AuditEntry[] | null>(null);

  useEffect(() => {
    getTenantAudit(150)
      .then(setRows)
      .catch((e) => {
        setRows([]);
        toast(e.message, "error");
      });
  }, [toast]);

  if (!rows) return <Loading />;

  return (
    <>
      <PageHeader title="Audit log" subtitle="Security-relevant events in this workspace." />
      {rows.length === 0 ? (
        <Empty>No audit entries yet.</Empty>
      ) : (
        <TableWrap
          head={
            <>
              <th>When</th>
              <th>Actor</th>
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
              <td>{r.actor}</td>
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
