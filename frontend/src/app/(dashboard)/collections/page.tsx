"use client";

import { useEffect, useMemo, useState } from "react";
import { listDocuments } from "@/lib/api/documents";
import type { DocumentRow } from "@/lib/types";
import { Card, Empty, Loading, PageHeader, StatusBadge, TableWrap } from "@/components/ui";
import { useToast } from "@/components/Toast";

export default function CollectionsPage() {
  const { toast } = useToast();
  const [docs, setDocs] = useState<DocumentRow[] | null>(null);

  useEffect(() => {
    listDocuments()
      .then(setDocs)
      .catch((e) => {
        setDocs([]);
        toast(e.message, "error");
      });
  }, [toast]);

  const groups = useMemo(() => {
    const map = new Map<string, DocumentRow[]>();
    (docs || []).forEach((d) => {
      const key = d.department?.trim() || "Unfiled";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(d);
    });
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [docs]);

  const tags = useMemo(() => {
    const counts = new Map<string, number>();
    (docs || []).forEach((d) => (d.tags || []).forEach((t) => counts.set(t, (counts.get(t) || 0) + 1)));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [docs]);

  if (!docs) return <Loading />;

  return (
    <>
      <PageHeader
        title="Collections"
        subtitle="Your knowledge base organised by department, confidentiality and tags."
      />

      {docs.length === 0 ? (
        <Empty>No documents indexed yet.</Empty>
      ) : (
        <div className="stack">
          {tags.length > 0 && (
            <Card title="Tags">
              <div className="chips">
                {tags.map(([t, n]) => (
                  <span key={t} className="chip" style={{ cursor: "default" }}>
                    {t} <span className="muted">· {n}</span>
                  </span>
                ))}
              </div>
            </Card>
          )}

          {groups.map(([dept, list]) => {
            const ready = list.filter((d) => d.status === "ready").length;
            return (
              <div key={dept}>
                <div className="spread" style={{ marginBottom: 8 }}>
                  <div className="card-title" style={{ marginBottom: 0 }}>
                    {dept}
                  </div>
                  <span className="badge">
                    {ready}/{list.length} ready
                  </span>
                </div>
                <TableWrap
                  head={
                    <>
                      <th>File</th>
                      <th>Confidentiality</th>
                      <th>Status</th>
                      <th>Chunks</th>
                    </>
                  }
                >
                  {list.map((d) => (
                    <tr key={d.id}>
                      <td style={{ fontWeight: 600 }}>{d.filename}</td>
                      <td>
                        <span className="badge blue">{d.confidentiality}</span>
                      </td>
                      <td>
                        <StatusBadge value={d.status} />
                      </td>
                      <td>{d.chunks || "—"}</td>
                    </tr>
                  ))}
                </TableWrap>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
