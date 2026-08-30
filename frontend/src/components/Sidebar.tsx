"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ComponentType, SVGProps } from "react";
import type { CurrentUser, Permission } from "@/lib/types";
import { can } from "@/lib/auth/permissions";
import {
  IconAsk,
  IconAudit,
  IconBuilding,
  IconCollections,
  IconDocs,
  IconGauge,
  IconHistory,
  IconInsights,
  IconLock,
  IconModel,
  IconPlug,
  IconSettings,
  IconUsers,
} from "./icons";

type Icon = ComponentType<SVGProps<SVGSVGElement>>;
interface NavItem {
  href: string;
  label: string;
  icon: Icon;
  perm?: Permission; // undefined → always visible
}
interface NavSection {
  label: string;
  items: NavItem[];
}

const SECTIONS: NavSection[] = [
  {
    label: "Platform",
    items: [
      { href: "/platform/overview", label: "Overview", icon: IconInsights, perm: "platform.read" },
      { href: "/platform/workspaces", label: "Workspaces", icon: IconBuilding, perm: "tenant.manage" },
      { href: "/platform/users", label: "All users", icon: IconUsers, perm: "platform.read" },
      { href: "/platform/audit", label: "Audit log", icon: IconAudit, perm: "platform.read" },
      { href: "/observability", label: "Observability", icon: IconGauge, perm: "observability.read" },
    ],
  },
  {
    label: "Workspace",
    items: [
      { href: "/ask", label: "Ask", icon: IconAsk, perm: "query.run" },
      { href: "/history", label: "History", icon: IconHistory, perm: "query.run" },
      { href: "/documents", label: "Documents", icon: IconDocs, perm: "document.read" },
      { href: "/collections", label: "Collections", icon: IconCollections, perm: "document.read" },
      { href: "/insights", label: "Insights", icon: IconInsights, perm: "insights.read" },
    ],
  },
  {
    label: "Administration",
    items: [
      { href: "/users", label: "Users", icon: IconUsers, perm: "user.manage" },
      { href: "/audit", label: "Audit log", icon: IconAudit, perm: "audit.read" },
      { href: "/connectors", label: "Data connectors", icon: IconPlug, perm: "data_connector.manage" },
      { href: "/model-connectors", label: "Model connectors", icon: IconModel, perm: "model_connector.manage" },
      { href: "/settings", label: "Settings", icon: IconSettings, perm: "settings.write" },
      { href: "/observability", label: "Observability", icon: IconGauge, perm: "observability.read" },
    ],
  },
  {
    label: "Account",
    items: [{ href: "/change-password", label: "Change password", icon: IconLock }],
  },
];

function sectionsFor(user: CurrentUser): NavSection[] {
  return SECTIONS.map((sec) => ({
    ...sec,
    items: sec.items.filter((it) => !it.perm || can(user, it.perm)),
  })).filter((sec) => sec.items.length > 0);
}

export function Sidebar({ user, open }: { user: CurrentUser; open: boolean }) {
  const pathname = usePathname();
  const sections = sectionsFor(user);

  return (
    <aside className={`sidebar${open ? " open" : ""}`}>
      <div className="sidebar-brand">
        <IconGauge width={20} height={20} />
        KnowledgeDesk
      </div>
      {sections.map((sec) => (
        <div key={sec.label}>
          <div className="sidebar-section">{sec.label}</div>
          {sec.items.map((item) => {
            const active = pathname === item.href || pathname.startsWith(item.href + "/");
            const Ico = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-item${active ? " active" : ""}`}
              >
                <Ico />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </div>
      ))}
    </aside>
  );
}
