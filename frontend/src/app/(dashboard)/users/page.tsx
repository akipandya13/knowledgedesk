"use client";

import { useCallback, useEffect, useState } from "react";
import { createUser, listUsers, resetPassword, updateUser } from "@/lib/api/users";
import type { Role, UserRow } from "@/lib/types";
import { useAuth } from "@/lib/auth/AuthProvider";
import { Empty, Loading, PageHeader, TableWrap, fmtDate } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { useToast } from "@/components/Toast";

export default function UsersPage() {
  const { user, hasPermission } = useAuth();
  const { toast } = useToast();
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ email: "", full_name: "", role: "member" as Role, password: "" });
  const [tempPw, setTempPw] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    listUsers()
      .then(setRows)
      .catch((e) => {
        setRows([]);
        toast(e.message, "error");
      });
  }, [toast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function submitCreate() {
    setBusy(true);
    try {
      const res = await createUser({
        email: form.email.trim().toLowerCase(),
        full_name: form.full_name.trim(),
        role: form.role,
        password: form.password || undefined,
      });
      if (res.temporary_password) setTempPw(res.temporary_password);
      else setShowCreate(false);
      toast("User created", "success");
      setForm({ email: "", full_name: "", role: "member", password: "" });
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Create failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(u: UserRow) {
    try {
      await updateUser(u.id, { is_active: !u.is_active });
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Update failed", "error");
    }
  }

  async function changeRole(u: UserRow, role: Role) {
    try {
      await updateUser(u.id, { role });
      toast("Role updated", "success");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Update failed", "error");
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

  if (!rows) return <Loading />;

  return (
    <>
      <PageHeader
        title="Users"
        subtitle="Manage members and admins of this workspace."
        actions={
          <button className="btn" onClick={() => { setTempPw(""); setShowCreate(true); }}>
            + Add user
          </button>
        }
      />

      {rows.length === 0 ? (
        <Empty>No users found.</Empty>
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
          {rows.map((u) => {
            const self = u.id === user?.id;
            return (
              <tr key={u.id}>
                <td style={{ fontWeight: 600 }}>{u.full_name || "—"}</td>
                <td>{u.email}</td>
                <td>
                  <select
                    value={u.role}
                    disabled={self}
                    onChange={(e) => changeRole(u, e.target.value as Role)}
                    style={{ width: 150 }}
                  >
                    <option value="member">member</option>
                    <option value="tenant_admin">tenant_admin</option>
                  </select>
                </td>
                <td>
                  <span className={`badge ${u.is_active ? "green" : "amber"}`}>
                    {u.is_active ? "active" : "disabled"}
                  </span>
                </td>
                <td className="small muted">{fmtDate(u.last_login_at)}</td>
                <td>
                  <div className="row" style={{ gap: 6 }}>
                    <button className="btn ghost sm" onClick={() => doReset(u)}>
                      Reset pw
                    </button>
                    <button className="btn ghost sm" disabled={self} onClick={() => toggleActive(u)}>
                      {u.is_active ? "Disable" : "Enable"}
                    </button>
                    {hasPermission("audit.read") && (
                      <a className="btn ghost sm" href={`/audit?target_type=user&target_id=${u.id}`}>
                        History
                      </a>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </TableWrap>
      )}

      <Modal
        open={showCreate}
        title="Add user"
        onClose={() => setShowCreate(false)}
        footer={
          tempPw ? (
            <button className="btn" onClick={() => setShowCreate(false)}>
              Done
            </button>
          ) : (
            <>
              <button className="btn secondary" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
              <button className="btn" disabled={busy || !form.email} onClick={submitCreate}>
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
              </select>
            </div>
            <div className="form-group">
              <label>Password (blank → auto-generate)</label>
              <input
                type="password"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
              />
            </div>
          </>
        )}
      </Modal>
    </>
  );
}
