"use client";

import { useCallback, useEffect, useState } from "react";
import { createUser, listUsers, resetPassword } from "@/lib/api/users";
import { listTenants } from "@/lib/api/platform";
import type { Role, TenantRow, UserRow } from "@/lib/types";
import { Empty, Loading, PageHeader, TableWrap, fmtDate } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { useToast } from "@/components/Toast";

export default function PlatformUsersPage() {
  const { toast } = useToast();
  const [tenants, setTenants] = useState<TenantRow[]>([]);
  const [scope, setScope] = useState<string>(""); // "" = platform admins
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [open, setOpen] = useState(false);
  const [tempPw, setTempPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    email: "",
    full_name: "",
    role: "member" as Role,
    tenant_slug: "",
  });

  const refresh = useCallback(() => {
    listUsers(scope || undefined)
      .then(setRows)
      .catch((e) => {
        setRows([]);
        toast(e.message, "error");
      });
  }, [scope, toast]);

  useEffect(() => {
    listTenants().then(setTenants).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function submit() {
    setBusy(true);
    try {
      const body: Parameters<typeof createUser>[0] = {
        email: form.email.trim().toLowerCase(),
        full_name: form.full_name.trim(),
        role: form.role,
      };
      if (form.role !== "superadmin") body.tenant_slug = form.tenant_slug || undefined;
      const res = await createUser(body);
      if (res.temporary_password) setTempPw(res.temporary_password);
      else setOpen(false);
      toast("User created", "success");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Create failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function doReset(u: UserRow) {
    if (!confirm(`Reset password for ${u.email}?`)) return;
    try {
      const res = await resetPassword(u.id);
      toast(`Temp password: ${res.temporary_password}`, "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Reset failed", "error");
    }
  }

  return (
    <>
      <PageHeader
        title="All users"
        subtitle="Platform admins and per-workspace users."
        actions={
          <button
            className="btn"
            onClick={() => {
              setTempPw("");
              setForm({ email: "", full_name: "", role: "member", tenant_slug: tenants[0]?.slug || "" });
              setOpen(true);
            }}
          >
            + Add user
          </button>
        }
      />

      <div className="form-group" style={{ maxWidth: 320 }}>
        <label>Scope</label>
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="">Platform admins</option>
          {tenants.map((t) => (
            <option key={t.slug} value={t.slug}>
              {t.name} ({t.slug})
            </option>
          ))}
        </select>
      </div>

      {!rows ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty>No users in this scope.</Empty>
      ) : (
        <TableWrap
          head={
            <>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>Last login</th>
              <th />
            </>
          }
        >
          {rows.map((u) => (
            <tr key={u.id}>
              <td style={{ fontWeight: 600 }}>{u.full_name || "—"}</td>
              <td>{u.email}</td>
              <td>
                <span className="badge blue">{u.role}</span>
              </td>
              <td>
                <span className={`badge ${u.is_active ? "green" : "amber"}`}>
                  {u.is_active ? "active" : "disabled"}
                </span>
              </td>
              <td className="small muted">{fmtDate(u.last_login_at)}</td>
              <td>
                <button className="btn ghost sm" onClick={() => doReset(u)}>
                  Reset pw
                </button>
              </td>
            </tr>
          ))}
        </TableWrap>
      )}

      <Modal
        open={open}
        title="Add user"
        onClose={() => setOpen(false)}
        footer={
          tempPw ? (
            <button className="btn" onClick={() => setOpen(false)}>
              Done
            </button>
          ) : (
            <>
              <button className="btn secondary" onClick={() => setOpen(false)}>
                Cancel
              </button>
              <button className="btn" disabled={busy || !form.email} onClick={submit}>
                {busy ? "Creating…" : "Create user"}
              </button>
            </>
          )
        }
      >
        {tempPw ? (
          <div className="notice green">
            User created. Temporary password (shown once):
            <div className="mono" style={{ marginTop: 6, fontSize: 14 }}>
              {tempPw}
            </div>
          </div>
        ) : (
          <>
            <div className="form-group">
              <label>Full name</label>
              <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Work email</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Role</label>
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                <option value="member">Member</option>
                <option value="tenant_admin">Workspace admin</option>
                <option value="superadmin">Platform superadmin</option>
              </select>
            </div>
            {form.role !== "superadmin" && (
              <div className="form-group">
                <label>Workspace</label>
                <select
                  value={form.tenant_slug}
                  onChange={(e) => setForm({ ...form, tenant_slug: e.target.value })}
                >
                  {tenants.map((t) => (
                    <option key={t.slug} value={t.slug}>
                      {t.name} ({t.slug})
                    </option>
                  ))}
                </select>
              </div>
            )}
          </>
        )}
      </Modal>
    </>
  );
}
