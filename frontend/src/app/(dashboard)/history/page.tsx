"use client";

import { useEffect, useState } from "react";
import { getRecentQueries } from "@/lib/api/admin";
import type { RecentQuery } from "@/lib/types";
import { Empty, Loading, PageHeader, StatusBadge, TableWrap, fmtDate } from "@/components/ui";
import { useToast } from "@/components/Toast";

export default function HistoryPage() {
  const { toast } = useToast();
  const [rows, setRows] = useState<RecentQuery[] | null>(null);

  useEffect(() => {
    getRecentQueries(100)
      .then(setRows)
      .catch((e) => {
        setRows([]);
        toast(e.message, "error");
      });
  }, [toast]);

  if (!rows) return <Loading />;

  return (
    <>
      <PageHeader title="Query history" subtitle="Recent questions asked in this workspace." />
      {rows.length === 0 ? (
        <Empty>No questions asked yet.</Empty>
      ) : (
        <TableWrap
          head={
            <>
              <th>Question</th>
              <th>Mode</th>
              <th>Confidence</th>
              <th>Latency</th>
              <th>Feedback</th>
              <th>When</th>
            </>
          }
        >
          {rows.map((r) => (
            <tr key={r.id}>
              <td style={{ maxWidth: 460 }}>{r.question}</td>
              <td>
                <StatusBadge value={r.mode} />
              </td>
              <td>{Math.round((r.confidence || 0) * 100)}%</td>
              <td>{r.latency_ms} ms</td>
              <td>{r.feedback === 1 ? "👍" : r.feedback === -1 ? "👎" : "—"}</td>
              <td className="small muted">{fmtDate(r.created_at)}</td>
            </tr>
          ))}
        </TableWrap>
      )}
    </>
  );
}
