"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { ROLE_HOME } from "@/lib/config";
import type { Permission } from "@/lib/types";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { Loading } from "@/components/ui";

// Route prefix → permission needed to open it. The backend enforces the real
// thing; this just keeps people out of pages that would 403 anyway.
const ROUTE_PERMISSION: { prefix: string; perm: Permission }[] = [
  { prefix: "/ask", perm: "query.run" },
  { prefix: "/history", perm: "query.run" },
  { prefix: "/documents", perm: "document.read" },
  { prefix: "/collections", perm: "document.read" },
  { prefix: "/insights", perm: "insights.read" },
  { prefix: "/users", perm: "user.manage" },
  { prefix: "/audit", perm: "audit.read" },
  { prefix: "/connectors", perm: "data_connector.manage" },
  { prefix: "/model-connectors", perm: "model_connector.manage" },
  { prefix: "/settings", perm: "settings.write" },
  { prefix: "/observability", perm: "observability.read" },
  { prefix: "/access", perm: "access.manage" },
  { prefix: "/platform", perm: "platform.read" },
];

const ALWAYS_ALLOWED = ["/change-password", "/security"];

function makeAllowed(has: (p: Permission) => boolean) {
  return (pathname: string): boolean => {
    if (ALWAYS_ALLOWED.some((p) => pathname === p || pathname.startsWith(p + "/"))) return true;
    const match = ROUTE_PERMISSION.find(
      ({ prefix }) => pathname === prefix || pathname.startsWith(prefix + "/"),
    );
    return match ? has(match.perm) : false;
  };
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const { user, loading, hasPermission } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [navOpen, setNavOpen] = useState(false);
  const allowed = makeAllowed(hasPermission);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      const next = encodeURIComponent(pathname);
      router.replace(`/login?next=${next}`);
      return;
    }
    if (user.force_password_change) {
      router.replace("/change-password");
      return;
    }
    if (!allowed(pathname)) {
      router.replace(ROLE_HOME[user.role] || "/ask");
    }
  }, [user, loading, pathname, router, hasPermission]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => setNavOpen(false), [pathname]);

  if (loading || !user || user.force_password_change || !allowed(pathname)) {
    return <Loading label="Loading workspace…" />;
  }

  return (
    <div className="app-shell">
      <Sidebar user={user} open={navOpen} />
      <div className="main">
        <TopBar onToggleNav={() => setNavOpen((v) => !v)} />
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
