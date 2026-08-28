"use client";

import { useEffect, useState } from "react";
import { getGaps, getReadiness, getRecentQueries, getStats } from "@/lib/api/admin";
import type { AdminStats, KnowledgeGap, RecentQuery } from "@/lib/types";
import {
  Card,
  Empty,
  Loading,
  PageHeader,
  StatCard,
  StatusBadge,
  TableWrap,
  fmtDate,
} from "@/components/ui";
import { useToast } from "@/components/Toast";

export default function InsightsPage() {
  const { toast } = useToast();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [queries, setQueries] = useState<RecentQuery[]>([]);
  const [gaps, setGaps] = useState<KnowledgeGap[]>([]);
  const [readiness, setReadiness] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    Promise.all([getStats(), getRecentQueries(25), getGaps(10), getReadiness()])
      .then(([s, q, g, r]) => {
        setStats(s);
        setQueries(q);
        setGaps(g);
        setReadiness(r);
      })
      .catch((e) => toast(e.message, "error"));
  }, [toast]);

  if (!stats) return <Loading />;

  const checks = (readiness?.checks || {}) as Record<string, string>;

  return (
    <>
      <PageHeader title="Insights" subtitle="Adoption, answer quality and knowledge gaps for this workspace." />

      <div className="stat-grid">
        <StatCard value={stats.documents_ready} label="Documents ready" />
        <StatCard value={stats.chunks_total} label="Indexed chunks" />
        <StatCard value={stats.queries_total} label="Questions asked" />
        <StatCard value={stats.queries_answered} label="Answered" />
        <StatCard value={stats.knowledge_gaps} label="Knowledge gaps" />
        <StatCard value={`${stats.avg_latency_ms} ms`} label="Avg latency" />
        <StatCard value={stats.feedback_helpful} label="👍 Helpful" />
        <StatCard value={stats.feedback_unhelpful} label="👎 Not helpful" />
      </div>

      <div className="two-col">
        <Card title="Knowledge gaps (unanswered questions)">
          {gaps.length === 0 ? (
            <Empty>No gaps logged — every question found an answer.</Empty>
          ) : (
            <div className="stack" style={{ gap: 8 }}>
              {gaps.map((g, i) => (
                <div key={i} className="notice" style={{ marginBottom: 0 }}>
                  <div>{g.question}</div>
                  <div className="small muted">{fmtDate(g.created_at)}</div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Rollout readiness">
          {readiness ? (
            <div className="stack" style={{ gap: 8 }}>
              <div className="row">
                <span className="badge blue">{String(readiness.rollout_stage)}</span>
              </div>
              {Object.entries(checks).map(([k, v]) => (
                <div key={k} className="spread small">
                  <span className="muted">{k.replace(/_/g, " ")}</span>
                  <StatusBadge value={String(v)} />
                </div>
              ))}
              {typeof readiness.recommended_next_step === "string" && (
                <div className="notice" style={{ marginBottom: 0 }}>
                  Next: {readiness.recommended_next_step}
                </div>
              )}
            </div>
          ) : (
            <Empty>Unavailable.</Empty>
          )}
        </Card>
      </div>

      <div style={{ marginTop: 18 }}>
        <div className="card-title">Recent questions</div>
        {queries.length === 0 ? (
          <Empty>No questions yet.</Empty>
        ) : (
          <TableWrap
            head={
              <>
                <th>Question</th>
                <th>Mode</th>
                <th>Confidence</th>
                <th>Latency</th>
                <th>When</th>
              </>
            }
          >
            {queries.map((q) => (
              <tr key={q.id}>
                <td style={{ maxWidth: 460 }}>{q.question}</td>
                <td>
                  <StatusBadge value={q.mode} />
                </td>
                <td>{Math.round((q.confidence || 0) * 100)}%</td>
                <td>{q.latency_ms} ms</td>
                <td className="small muted">{fmtDate(q.created_at)}</td>
              </tr>
            ))}
          </TableWrap>
        )}
      </div>
    </>
  );
}
