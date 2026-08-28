"use client";

import { useEffect, useState } from "react";
import { getHealth } from "@/lib/api/health";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { HealthStatus } from "@/lib/types";
import { IconLogout, IconMenu } from "./icons";

export function TopBar({ onToggleNav }: { onToggleNav: () => void }) {
  const { user, signOut } = useAuth();
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    let live = true;
    const tick = () => {
      getHealth()
        .then((h) => live && setHealth(h))
        .catch(() => undefined);
    };
    tick();
    const id = setInterval(tick, 15000);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, []);

  const initials = (user?.full_name || user?.email || "?")
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");

  const dot = (state?: string) =>
    state === "ok" ? "ok" : state === "disabled" ? "warn" : "down";

  return (
    <header className="topbar">
      <button className="btn ghost sm nav-toggle" onClick={onToggleNav} aria-label="Toggle navigation">
        <IconMenu />
      </button>

      <div className="row small muted" style={{ gap: 16 }}>
        {health && (
          <>
            <span className="health-dot">
              <span className={`dot ${dot(health.qdrant)}`} /> Vector index
            </span>
            <span className="health-dot">
              <span className={`dot ${dot(health.llm)}`} /> LLM ({health.llm_model || health.llm_provider})
            </span>
          </>
        )}
      </div>

      <div className="topbar-user">
        <div className="avatar">{initials}</div>
        <div>
          <div style={{ fontWeight: 600 }}>{user?.full_name || user?.email}</div>
          <div className="small muted">
            {user?.role}
            {user?.tenant ? ` · ${user.tenant.name}` : ""}
          </div>
        </div>
        <button className="btn ghost sm" onClick={() => void signOut()} title="Sign out">
          <IconLogout />
        </button>
      </div>
    </header>
  );
}
