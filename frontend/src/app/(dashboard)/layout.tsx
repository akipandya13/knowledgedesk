"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { can } from "@/lib/auth/permissions";
import { ROLE_HOME } from "@/lib/config";
import type { CurrentUser, Permission } from "@/lib/types";
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
  { prefix: "/platform", perm: "platform.read" },
];

const ALWAYS_ALLOWED = ["/change-password"];

function allowed(pathname: string, user: CurrentUser): boolean {
  if (ALWAYS_ALLOWED.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    return true;
  }
  const match = ROUTE_PERMISSION.find(
    ({ prefix }) => pathname === prefix || pathname.startsWith(prefix + "/"),
  );
  return match ? can(user, match.perm) : false;
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [navOpen, setNavOpen] = useState(false);

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
    if (!allowed(pathname, user)) {
      router.replace(ROLE_HOME[user.role] || "/ask");
    }
  }, [user, loading, pathname, router]);

  useEffect(() => setNavOpen(false), [pathname]);

  if (loading || !user || user.force_password_change || !allowed(pathname, user)) {
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
