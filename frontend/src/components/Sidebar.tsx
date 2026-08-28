"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ComponentType, SVGProps } from "react";
import type { Role } from "@/lib/types";
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
}
interface NavSection {
  label: string;
  items: NavItem[];
}

function sectionsFor(role: Role): NavSection[] {
  if (role === "superadmin") {
    return [
      {
        label: "Platform",
        items: [
          { href: "/platform/overview", label: "Overview", icon: IconInsights },
          { href: "/platform/workspaces", label: "Workspaces", icon: IconBuilding },
          { href: "/platform/users", label: "All users", icon: IconUsers },
          { href: "/platform/audit", label: "Audit log", icon: IconAudit },
        ],
      },
      { label: "Account", items: [{ href: "/change-password", label: "Change password", icon: IconLock }] },
    ];
  }

  const workspace: NavSection = {
    label: "Workspace",
    items: [
      { href: "/ask", label: "Ask", icon: IconAsk },
      { href: "/history", label: "History", icon: IconHistory },
      { href: "/documents", label: "Documents", icon: IconDocs },
      { href: "/collections", label: "Collections", icon: IconCollections },
      { href: "/insights", label: "Insights", icon: IconInsights },
    ],
  };

  const sections: NavSection[] = [workspace];
  if (role === "tenant_admin") {
    sections.push({
      label: "Administration",
      items: [
        { href: "/users", label: "Users", icon: IconUsers },
        { href: "/audit", label: "Audit log", icon: IconAudit },
        { href: "/connectors", label: "Data connectors", icon: IconPlug },
        { href: "/model-connectors", label: "Model connectors", icon: IconModel },
        { href: "/settings", label: "Settings", icon: IconSettings },
      ],
    });
  }
  sections.push({
    label: "Account",
    items: [{ href: "/change-password", label: "Change password", icon: IconLock }],
  });
  return sections;
}

export function Sidebar({ role, open }: { role: Role; open: boolean }) {
  const pathname = usePathname();
  const sections = sectionsFor(role);

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
