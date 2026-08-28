"use client";

import { useEffect, useState } from "react";
import { getPlatformStats, type PlatformStats } from "@/lib/api/platform";
import { Loading, PageHeader, StatCard } from "@/components/ui";
import { useToast } from "@/components/Toast";

export default function PlatformOverviewPage() {
  const { toast } = useToast();
  const [stats, setStats] = useState<PlatformStats | null>(null);

  useEffect(() => {
    getPlatformStats()
      .then(setStats)
      .catch((e) => toast(e.message, "error"));
  }, [toast]);

  if (!stats) return <Loading />;

  return (
    <>
      <PageHeader title="Platform overview" subtitle="Aggregate metrics across every workspace." />
      <div className="stat-grid">
        <StatCard value={stats.tenants} label="Workspaces" />
        <StatCard value={stats.users} label="Users" />
        <StatCard value={stats.documents} label="Documents" />
        <StatCard value={stats.queries_total} label="Total questions" />
      </div>
      <div className="notice">
        The platform operator has no access to workspace document content — only lifecycle, users and audit.
      </div>
    </>
  );
}
