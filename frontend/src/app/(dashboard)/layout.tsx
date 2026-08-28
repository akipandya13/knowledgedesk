"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { ROLE_HOME } from "@/lib/config";
import type { Role } from "@/lib/types";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { Loading } from "@/components/ui";

const MEMBER_ROUTES = ["/ask", "/history", "/documents", "/collections", "/insights", "/change-password"];
const TENANT_ADMIN_ROUTES = [
  ...MEMBER_ROUTES,
  "/users",
  "/audit",
  "/connectors",
  "/model-connectors",
  "/settings",
];
const SUPERADMIN_ROUTES = ["/platform", "/change-password"];

function allowed(pathname: string, role: Role): boolean {
  const list =
    role === "superadmin"
      ? SUPERADMIN_ROUTES
      : role === "tenant_admin"
        ? TENANT_ADMIN_ROUTES
        : MEMBER_ROUTES;
  return list.some((p) => pathname === p || pathname.startsWith(p + "/"));
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
    if (!allowed(pathname, user.role)) {
      router.replace(ROLE_HOME[user.role] || "/ask");
    }
  }, [user, loading, pathname, router]);

  useEffect(() => setNavOpen(false), [pathname]);

  if (loading || !user || user.force_password_change || !allowed(pathname, user.role)) {
    return <Loading label="Loading workspace…" />;
  }

  return (
    <div className="app-shell">
      <Sidebar role={user.role} open={navOpen} />
      <div className="main">
        <TopBar onToggleNav={() => setNavOpen((v) => !v)} />
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
