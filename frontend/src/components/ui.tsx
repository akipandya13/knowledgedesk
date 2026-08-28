"use client";

import type { ReactNode } from "react";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="spread" style={{ marginBottom: 22, alignItems: "flex-start" }}>
      <div>
        <div className="page-title">{title}</div>
        {subtitle && <div className="page-subtitle" style={{ marginBottom: 0 }}>{subtitle}</div>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export function Card({ title, children, style }: { title?: string; children: ReactNode; style?: React.CSSProperties }) {
  return (
    <div className="card" style={style}>
      {title && <div className="card-title">{title}</div>}
      {children}
    </div>
  );
}

export function StatCard({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="stat-card">
      <div className="stat-val">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

const TONE: Record<string, string> = {
  ready: "green",
  ok: "green",
  processing: "amber",
  queued: "amber",
  failed: "red",
  down: "red",
  deleted: "red",
  disabled: "amber",
};

export function StatusBadge({ value }: { value: string }) {
  const tone = TONE[value?.toLowerCase()] || "blue";
  return <span className={`badge ${tone}`}>{value}</span>;
}

export function Notice({ kind = "info", children }: { kind?: "info" | "amber" | "red" | "green"; children: ReactNode }) {
  return <div className={`notice ${kind === "info" ? "" : kind}`}>{children}</div>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="center-load">
      <span className="spinner" style={{ marginRight: 10 }} /> {label}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function TableWrap({ head, children }: { head: ReactNode; children: ReactNode }) {
  return (
    <div className="table-wrap">
      <div className="table-scroll">
        <table>
          <thead>
            <tr>{head}</tr>
          </thead>
          <tbody>{children}</tbody>
        </table>
      </div>
    </div>
  );
}

export function fmtDate(s: string | null): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return s;
  }
}

export function fmtBytes(b: number): string {
  if (!b) return "0 B";
  const k = 1024;
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(b) / Math.log(k)));
  return `${(b / k ** i).toFixed(1)} ${units[i]}`;
}
