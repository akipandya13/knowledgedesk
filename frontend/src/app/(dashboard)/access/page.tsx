"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api/access";
import { listUsers, updateUser } from "@/lib/api/users";
import type {
  AccessCatalog,
  AccessGroup,
  ApiKeyRow,
  AuthPolicy,
  CustomRole,
  GrantEffect,
  SsoConfig,
  SubjectAssignments,
  UserRow,
} from "@/lib/types";
import { Card, Empty, Loading, Notice, PageHeader, TableWrap, fmtDate } from "@/components/ui";
import { IconTrash } from "@/components/icons";
import { useToast } from "@/components/Toast";

type Tab = "roles" | "groups" | "users" | "policy" | "auth";
const TABS: { id: Tab; label: string }[] = [
  { id: "roles", label: "Custom roles" },
  { id: "groups", label: "Groups" },
  { id: "users", label: "User access" },
  { id: "auth", label: "Authentication" },
  { id: "policy", label: "Confidentiality" },
];

export default function AccessPage() {
  const { toast } = useToast();
  const [tab, setTab] = useState<Tab>("roles");
  const [catalog, setCatalog] = useState<AccessCatalog | null>(null);
  const [users, setUsers] = useState<UserRow[]>([]);

  useEffect(() => {
    api.getAccessCatalog().then(setCatalog).catch((e) => toast(e.message, "error"));
    listUsers().then(setUsers).catch((e) => toast(e.message, "error"));
  }, [toast]);

  if (!catalog) return <Loading label="Loading access model…" />;

  return (
    <>
      <PageHeader
        title="Access control"
        subtitle="Custom roles, groups, per-user grants and confidentiality clearance — layered on the built-in roles."
      />
      <div className="chips" style={{ marginBottom: 14 }}>
        {TABS.map((t) => (
          <button key={t.id} className={`chip${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "roles" && <RolesTab catalog={catalog} toast={toast} />}
      {tab === "groups" && <GroupsTab users={users} toast={toast} />}
      {tab === "users" && <UsersTab catalog={catalog} users={users} setUsers={setUsers} toast={toast} />}
      {tab === "auth" && <AuthTab toast={toast} />}
      {tab === "policy" && <PolicyTab toast={toast} />}
    </>
  );
}

type Toast = (m: string, k?: "success" | "error" | "warning" | "info") => void;

// ── Roles ────────────────────────────────────────────────────────
function RolesTab({ catalog, toast }: { catalog: AccessCatalog; toast: Toast }) {
  const [roles, setRoles] = useState<CustomRole[] | null>(null);
  const [key, setKey] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const load = useCallback(() => api.getRoles().then(setRoles).catch((e) => toast(e.message, "error")), [toast]);
  useEffect(() => { load(); }, [load]);

  const toggle = (p: string) =>
    setPicked((s) => {
      const n = new Set(s);
      n.has(p) ? n.delete(p) : n.add(p);
      return n;
    });

  async function create() {
    try {
      await api.createRole({ key: key.trim(), name: key.trim(), permissions: [...picked] });
      setKey(""); setPicked(new Set());
      toast("Role created", "success");
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    }
  }

  if (!roles) return <Loading />;
  return (
    <>
      <Card title="New role" style={{ marginBottom: 16 }}>
        <div className="form-group">
          <label>Key</label>
          <input value={key} onChange={(e) => setKey(e.target.value)} placeholder="e.g. auditor" />
        </div>
        <label>Permissions</label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, margin: "6px 0 12px" }}>
          {catalog.permissions.map((p) => (
            <label key={p.key} className="small" style={{ display: "flex", gap: 6, alignItems: "start" }}>
              <input type="checkbox" checked={picked.has(p.key)} onChange={() => toggle(p.key)} />
              <span><span className="mono">{p.key}</span><br /><span className="muted">{p.description}</span></span>
            </label>
          ))}
        </div>
        <button className="btn" disabled={!key.trim() || picked.size === 0} onClick={create}>Create role</button>
      </Card>

      {roles.length === 0 ? (
        <Empty>No custom roles yet.</Empty>
      ) : (
        <TableWrap head={<><th>Key</th><th>Permissions</th><th /></>}>
          {roles.map((r) => (
            <tr key={r.id}>
              <td style={{ fontWeight: 600 }}>{r.key}</td>
              <td className="small mono">{r.permissions.join(", ") || "—"}</td>
              <td>
                <button className="btn danger sm" aria-label="Delete"
                  onClick={() => api.deleteRole(r.id).then(load).catch((e) => toast(e.message, "error"))}>
                  <IconTrash />
                </button>
              </td>
            </tr>
          ))}
        </TableWrap>
      )}
    </>
  );
}

// ── Groups ───────────────────────────────────────────────────────
function GroupsTab({ users, toast }: { users: UserRow[]; toast: Toast }) {
  const [groups, setGroups] = useState<AccessGroup[] | null>(null);
  const [name, setName] = useState("");
  const load = useCallback(() => api.getGroups().then(setGroups).catch((e) => toast(e.message, "error")), [toast]);
  useEffect(() => { load(); }, [load]);

  if (!groups) return <Loading />;
  return (
    <>
      <Card title="New group" style={{ marginBottom: 16 }}>
        <div className="row">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Group name" style={{ flex: 1 }} />
          <button className="btn" disabled={!name.trim()}
            onClick={() => api.createGroup({ name: name.trim() }).then(() => { setName(""); load(); }).catch((e) => toast(e.message, "error"))}>
            Create
          </button>
        </div>
      </Card>
      {groups.length === 0 ? (
        <Empty>No groups yet.</Empty>
      ) : groups.map((g) => (
        <Card key={g.id} title={g.name} style={{ marginBottom: 12 }}>
          <div className="chips" style={{ marginBottom: 8 }}>
            {g.members.map((m) => (
              <span key={m.user_id} className="chip" style={{ cursor: "default" }}>
                {m.email}{" "}
                <button className="link-btn" onClick={() =>
                  api.removeGroupMember(g.id, m.user_id).then(load).catch((e) => toast(e.message, "error"))}>✕</button>
              </span>
            ))}
            {g.members.length === 0 && <span className="muted small">no members</span>}
          </div>
          <div className="row">
            <select id={`add-${g.id}`} defaultValue="">
              <option value="" disabled>Add member…</option>
              {users.filter((u) => !g.members.some((m) => m.user_id === u.id)).map((u) => (
                <option key={u.id} value={u.id}>{u.email}</option>
              ))}
            </select>
            <button className="btn secondary" onClick={() => {
              const el = document.getElementById(`add-${g.id}`) as HTMLSelectElement;
              if (el?.value) api.addGroupMember(g.id, Number(el.value)).then(load).catch((e) => toast(e.message, "error"));
            }}>Add</button>
            <button className="btn danger sm" style={{ marginLeft: "auto" }}
              onClick={() => api.deleteGroup(g.id).then(load).catch((e) => toast(e.message, "error"))}>
              <IconTrash />
            </button>
          </div>
        </Card>
      ))}
    </>
  );
}

// ── User access ──────────────────────────────────────────────────
function UsersTab({
  catalog, users, setUsers, toast,
}: { catalog: AccessCatalog; users: UserRow[]; setUsers: (u: UserRow[]) => void; toast: Toast }) {
  const [roles, setRoles] = useState<CustomRole[]>([]);
  const [sel, setSel] = useState<number | "">("");
  const [asg, setAsg] = useState<SubjectAssignments | null>(null);
  const [eff, setEff] = useState<string[]>([]);
  const [grantPerm, setGrantPerm] = useState("");
  const [grantEffect, setGrantEffect] = useState<GrantEffect>("allow");

  useEffect(() => { api.getRoles().then(setRoles).catch(() => undefined); }, []);

  const refresh = useCallback((uid: number) => {
    api.getAssignments("user", uid).then(setAsg).catch((e) => toast(e.message, "error"));
    api.effectiveFor(uid).then((r) => setEff(r.permissions)).catch(() => setEff([]));
  }, [toast]);

  useEffect(() => { if (typeof sel === "number") refresh(sel); }, [sel, refresh]);

  const user = useMemo(() => users.find((u) => u.id === sel), [users, sel]);

  async function setClearance(v: number) {
    if (typeof sel !== "number") return;
    try {
      const updated = await updateUser(sel, { clearance: v });
      setUsers(users.map((u) => (u.id === sel ? updated : u)));
      toast("Clearance updated", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    }
  }

  return (
    <>
      <Card title="Select user" style={{ marginBottom: 16 }}>
        <select value={sel} onChange={(e) => setSel(e.target.value ? Number(e.target.value) : "")}>
          <option value="">Choose a user…</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.email} ({u.role})</option>)}
        </select>
      </Card>

      {typeof sel === "number" && asg && user && (
        <>
          <Card title="Custom roles" style={{ marginBottom: 12 }}>
            <div className="chips" style={{ marginBottom: 8 }}>
              {asg.roles.map((r) => (
                <span key={r.assignment_id} className="chip" style={{ cursor: "default" }}>
                  {r.key}{" "}
                  <button className="link-btn" onClick={() =>
                    api.unassignRole(r.assignment_id).then(() => refresh(sel)).catch((e) => toast(e.message, "error"))}>✕</button>
                </span>
              ))}
              {asg.roles.length === 0 && <span className="muted small">none</span>}
            </div>
            <div className="row">
              <select id="assign-role" defaultValue="">
                <option value="" disabled>Assign role…</option>
                {roles.filter((r) => !asg.roles.some((x) => x.role_id === r.id)).map((r) => (
                  <option key={r.id} value={r.id}>{r.key}</option>
                ))}
              </select>
              <button className="btn secondary" onClick={() => {
                const el = document.getElementById("assign-role") as HTMLSelectElement;
                if (el?.value) api.assignRole("user", sel, Number(el.value)).then(() => refresh(sel)).catch((e) => toast(e.message, "error"));
              }}>Assign</button>
            </div>
          </Card>

          <Card title="Direct grants (deny overrides everything)" style={{ marginBottom: 12 }}>
            {asg.grants.length > 0 && (
              <TableWrap head={<><th>Permission</th><th>Effect</th><th /></>}>
                {asg.grants.map((g) => (
                  <tr key={g.id}>
                    <td className="mono">{g.permission}</td>
                    <td style={{ color: g.effect === "deny" ? "var(--red)" : undefined }}>{g.effect}</td>
                    <td><button className="btn danger sm" onClick={() =>
                      api.deleteGrant(g.id).then(() => refresh(sel)).catch((e) => toast(e.message, "error"))}><IconTrash /></button></td>
                  </tr>
                ))}
              </TableWrap>
            )}
            <div className="row" style={{ marginTop: 8 }}>
              <select value={grantPerm} onChange={(e) => setGrantPerm(e.target.value)} style={{ flex: 1 }}>
                <option value="">Permission…</option>
                {catalog.permissions.map((p) => <option key={p.key} value={p.key}>{p.key}</option>)}
              </select>
              <select value={grantEffect} onChange={(e) => setGrantEffect(e.target.value as GrantEffect)}>
                <option value="allow">allow</option>
                <option value="deny">deny</option>
              </select>
              <button className="btn" disabled={!grantPerm} onClick={() =>
                api.setGrant({ subject_type: "user", subject_id: sel, permission: grantPerm, effect: grantEffect })
                  .then(() => { setGrantPerm(""); refresh(sel); }).catch((e) => toast(e.message, "error"))}>Add</button>
            </div>
          </Card>

          <Card title="Confidentiality clearance" style={{ marginBottom: 12 }}>
            <div className="row">
              <select value={user.clearance} onChange={(e) => setClearance(Number(e.target.value))}>
                {Object.entries(catalog.confidentiality_levels).map(([name, lvl]) => (
                  <option key={name} value={lvl}>{name} ({lvl})</option>
                ))}
                <option value={100}>all (100)</option>
              </select>
              <span className="small muted">Only enforced when the workspace policy is on.</span>
            </div>
          </Card>

          <Card title="Effective permissions">
            <div className="small mono" style={{ lineHeight: 1.8 }}>
              {eff.length ? eff.map((p) => <span key={p} className="badge" style={{ marginRight: 6 }}>{p}</span>) : "—"}
            </div>
          </Card>
        </>
      )}
    </>
  );
}

// ── Authentication ──────────────────────────────────────────────
function AuthTab({ toast }: { toast: Toast }) {
  const [policy, setPolicy] = useState<AuthPolicy | null>(null);
  const [keys, setKeys] = useState<ApiKeyRow[] | null>(null);
  const [newKeyName, setNewKeyName] = useState("");
  const [freshKey, setFreshKey] = useState<string | null>(null);

  const loadPolicy = useCallback(() => api.getAuthPolicy().then(setPolicy).catch((e) => toast(e.message, "error")), [toast]);
  const loadKeys = useCallback(() => api.listApiKeys().then(setKeys).catch((e) => toast(e.message, "error")), [toast]);
  useEffect(() => { loadPolicy(); loadKeys(); }, [loadPolicy, loadKeys]);

  if (!policy || !keys) return <Loading />;
  const ssoEntitled = !!policy.entitlements.sso;

  return (
    <>
      <Card title="Sign-in policy" style={{ marginBottom: 16 }}>
        <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
          <input type="checkbox" checked={policy.mfa_required} onChange={(e) =>
            api.setAuthPolicy({ mfa_required: e.target.checked }).then(setPolicy).catch((err) => toast(err.message, "error"))} />
          Require two-factor authentication (members cannot disable it once set up)
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={policy.require_verified_email} onChange={(e) =>
            api.setAuthPolicy({ require_verified_email: e.target.checked }).then(setPolicy).catch((err) => toast(err.message, "error"))} />
          Require a verified email address before sign-in
        </label>
      </Card>

      <SsoCard entitled={ssoEntitled} toast={toast} />

      <Card title="API keys">
        <p className="small muted">Hashed at rest, named, optionally expiring. Shown once on creation.</p>
        {freshKey && (
          <Notice kind="amber">
            <strong>Copy this key now</strong> — it is not shown again:
            <div className="mono" style={{ marginTop: 4, wordBreak: "break-all" }}>{freshKey}</div>
          </Notice>
        )}
        <div className="row" style={{ margin: "8px 0" }}>
          <input value={newKeyName} onChange={(e) => setNewKeyName(e.target.value)} placeholder="Key name" style={{ flex: 1 }} />
          <button className="btn" disabled={!newKeyName.trim()} onClick={() =>
            api.createApiKey(newKeyName.trim()).then((r) => { setFreshKey(r.api_key); setNewKeyName(""); loadKeys(); })
              .catch((e) => toast(e.message, "error"))}>Create key</button>
        </div>
        {keys.length === 0 ? (
          <Empty>No API keys.</Empty>
        ) : (
          <TableWrap head={<><th>Name</th><th>Prefix</th><th>Last used</th><th>Expires</th><th /></>}>
            {keys.map((k) => (
              <tr key={k.id} style={{ opacity: k.revoked ? 0.5 : 1 }}>
                <td>{k.name}{k.revoked && " (revoked)"}</td>
                <td className="mono small">{k.prefix}…</td>
                <td className="small muted">{fmtDate(k.last_used_at)}</td>
                <td className="small muted">{k.expires_at ? fmtDate(k.expires_at) : "never"}</td>
                <td>{!k.revoked && (
                  <button className="btn danger sm" onClick={() =>
                    api.revokeApiKey(k.id).then(loadKeys).catch((e) => toast(e.message, "error"))}><IconTrash /></button>
                )}</td>
              </tr>
            ))}
          </TableWrap>
        )}
      </Card>
    </>
  );
}

function SsoCard({ entitled, toast }: { entitled: boolean; toast: Toast }) {
  const [cfg, setCfg] = useState<SsoConfig | null>(null);
  const [form, setForm] = useState({ display_name: "SSO", issuer: "", client_id: "", client_secret: "", allowed_domains: "", default_role: "member", is_active: false });
  useEffect(() => {
    api.getSso().then((c) => {
      setCfg(c);
      if (c.configured) setForm({
        display_name: c.display_name || "SSO", issuer: c.issuer || "", client_id: c.client_id || "",
        client_secret: "", allowed_domains: (c.allowed_domains || []).join(", "),
        default_role: c.default_role || "member", is_active: !!c.is_active,
      });
    }).catch(() => undefined);
  }, []);

  if (!cfg) return <Loading />;

  if (!entitled) {
    return (
      <Card title="Single sign-on (SSO)" style={{ marginBottom: 16 }}>
        <Notice kind="info">
          SSO with Google, Okta, Microsoft Entra or any OIDC provider is available on a paid plan.
          Contact your account team to enable the <span className="mono">sso</span> entitlement for this workspace.
        </Notice>
      </Card>
    );
  }

  return (
    <Card title="Single sign-on (OIDC)" style={{ marginBottom: 16 }}>
      <div className="two-col">
        <div className="form-group"><label>Button label</label>
          <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></div>
        <div className="form-group"><label>Default role for new users</label>
          <select value={form.default_role} onChange={(e) => setForm({ ...form, default_role: e.target.value })}>
            <option value="member">member</option><option value="tenant_admin">tenant_admin</option>
          </select></div>
      </div>
      <div className="form-group"><label>Issuer URL</label>
        <input value={form.issuer} placeholder="https://accounts.google.com" onChange={(e) => setForm({ ...form, issuer: e.target.value })} /></div>
      <div className="two-col">
        <div className="form-group"><label>Client ID</label>
          <input value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} /></div>
        <div className="form-group"><label>Client secret {cfg.client_secret_set && "(set — leave blank to keep)"}</label>
          <input type="password" value={form.client_secret} onChange={(e) => setForm({ ...form, client_secret: e.target.value })} /></div>
      </div>
      <div className="form-group"><label>Allowed email domains (comma-separated; blank = any)</label>
        <input value={form.allowed_domains} onChange={(e) => setForm({ ...form, allowed_domains: e.target.value })} placeholder="acme.com, acme.co.uk" /></div>
      <div className="hint">Redirect / callback URL to register with the IdP: <span className="mono">{cfg.callback_url}</span> (use your real origin)</div>
      <label style={{ display: "flex", gap: 8, alignItems: "center", margin: "8px 0" }}>
        <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Active
      </label>
      <button className="btn" onClick={() =>
        api.putSso({
          display_name: form.display_name, issuer: form.issuer, client_id: form.client_id,
          client_secret: form.client_secret || null,
          allowed_domains: form.allowed_domains.split(",").map((d) => d.trim()).filter(Boolean),
          default_role: form.default_role, is_active: form.is_active,
        }).then((c) => { setCfg(c); toast("SSO saved", "success"); }).catch((e) => toast(e.message, "error"))}>
        Save SSO connection
      </button>
      {cfg.configured && (
        <button className="btn danger" style={{ marginLeft: 8 }} onClick={() =>
          api.deleteSso().then(() => { setCfg({ configured: false, entitled: true }); toast("SSO removed", "success"); })
            .catch((e) => toast(e.message, "error"))}>Remove</button>
      )}
    </Card>
  );
}

// ── Policy ───────────────────────────────────────────────────────
function PolicyTab({ toast }: { toast: Toast }) {
  const [on, setOn] = useState<boolean | null>(null);
  useEffect(() => { api.getPolicy().then((p) => setOn(p.confidentiality_enforced)).catch((e) => toast(e.message, "error")); }, [toast]);
  if (on === null) return <Loading />;
  return (
    <Card title="Confidentiality enforcement">
      <Notice kind={on ? "green" : "info"}>
        {on
          ? "Enforced: users only see documents whose confidentiality level is within their clearance (owners, admins and explicit shares are exempt)."
          : "Off: the `confidentiality` field is metadata only and does not restrict access."}
      </Notice>
      <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
        <input type="checkbox" checked={on} onChange={(e) => {
          const v = e.target.checked;
          api.setPolicy(v).then(() => { setOn(v); toast("Policy updated", "success"); }).catch((err) => toast(err.message, "error"));
        }} />
        Enforce confidentiality clearance
      </label>
    </Card>
  );
}
