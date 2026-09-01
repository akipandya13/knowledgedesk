"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createTenant,
  deleteTenant,
  getTenant,
  listTenants,
  reactivateTenant,
  suspendTenant,
  updateTenant,
} from "@/lib/api/platform";
import type { TenantDetail, TenantRow } from "@/lib/types";
import { Empty, Loading, PageHeader, TableWrap, fmtDate } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { IconTrash } from "@/components/icons";
import { useToast } from "@/components/Toast";

// Mirror of authn.KNOWN_ENTITLEMENTS.
const ENTITLEMENTS = ["sso"];

export default function WorkspacesPage() {
  const { toast } = useToast();
  const [rows, setRows] = useState<TenantRow[] | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [manage, setManage] = useState<TenantDetail | null>(null);

  const refresh = useCallback(() => {
    listTenants()
      .then(setRows)
      .catch((e) => {
        setRows([]);
        toast(e.message, "error");
      });
  }, [toast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function doSuspend(t: TenantRow) {
    const reason = prompt(`Suspend "${t.name}"? Its users and API keys will be locked out (no data is lost).\n\nReason (optional):`);
    if (reason === null) return;
    try {
      await suspendTenant(t.slug, reason);
      toast("Workspace suspended", "success");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    }
  }

  async function doReactivate(t: TenantRow) {
    try {
      await reactivateTenant(t.slug);
      toast("Workspace reactivated", "success");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    }
  }

  async function doDelete(t: TenantRow) {
    if (!confirm(`Permanently delete "${t.name}" and ALL its users, documents, roles, keys, audit and vectors? This cannot be undone.`))
      return;
    try {
      const res = await deleteTenant(t.slug);
      const n = Object.values(res.rows_deleted).reduce((a, b) => a + b, 0);
      toast(`Workspace deleted (${n} rows removed)`, "success");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    }
  }

  if (!rows) return <Loading />;

  return (
    <>
      <PageHeader
        title="Workspaces"
        subtitle="Provision, configure, suspend and remove tenant organizations."
        actions={
          <button className="btn" onClick={() => setCreateOpen(true)}>
            + New workspace
          </button>
        }
      />

      {rows.length === 0 ? (
        <Empty>No workspaces yet.</Empty>
      ) : (
        <TableWrap
          head={
            <>
              <th>Name</th>
              <th>Slug</th>
              <th>Status</th>
              <th>Users</th>
              <th>Docs</th>
              <th>Created</th>
              <th />
            </>
          }
        >
          {rows.map((t) => (
            <tr key={t.id} style={{ opacity: t.status === "suspended" ? 0.6 : 1 }}>
              <td style={{ fontWeight: 600 }}>{t.name}</td>
              <td className="mono small">{t.slug}</td>
              <td>
                <span className={`badge ${t.status === "active" ? "green" : "amber"}`}>
                  {t.status}
                </span>
              </td>
              <td>{t.users}</td>
              <td>{t.documents}</td>
              <td className="small muted">{fmtDate(t.created_at)}</td>
              <td>
                <div className="row" style={{ gap: 6 }}>
                  <button
                    className="btn ghost sm"
                    onClick={() =>
                      getTenant(t.slug).then(setManage).catch((e) => toast(e.message, "error"))
                    }
                  >
                    Manage
                  </button>
                  {t.status === "active" ? (
                    <button className="btn ghost sm" onClick={() => doSuspend(t)}>
                      Suspend
                    </button>
                  ) : (
                    <button className="btn ghost sm" onClick={() => doReactivate(t)}>
                      Reactivate
                    </button>
                  )}
                  <button className="btn danger sm" onClick={() => doDelete(t)} aria-label="Delete">
                    <IconTrash />
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </TableWrap>
      )}

      {createOpen && (
        <CreateModal
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false);
            refresh();
          }}
          toast={toast}
        />
      )}
      {manage && (
        <ManageModal
          detail={manage}
          onClose={() => setManage(null)}
          onSaved={() => {
            setManage(null);
            refresh();
          }}
          toast={toast}
        />
      )}
    </>
  );
}

type Toast = (m: string, k?: "success" | "error" | "warning" | "info") => void;

function CreateModal({
  onClose,
  onCreated,
  toast,
}: {
  onClose: () => void;
  onCreated: () => void;
  toast: Toast;
}) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [ents, setEnts] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ api_key: string; slug: string; tempPw?: string } | null>(null);

  const toggle = (e: string) =>
    setEnts((s) => (s.includes(e) ? s.filter((x) => x !== e) : [...s, e]));

  async function submit() {
    setBusy(true);
    try {
      const res = await createTenant({
        name: name.trim(),
        slug: slug.trim().toLowerCase().replace(/\s+/g, "-"),
        admin_email: adminEmail.trim() || undefined,
        entitlements: ents,
      });
      setDone({
        api_key: res.api_key,
        slug: res.slug,
        tempPw: res.admin?.temporary_password,
      });
      toast("Workspace created", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Create failed", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      title="New workspace"
      onClose={done ? onCreated : onClose}
      footer={
        done ? (
          <button className="btn" onClick={onCreated}>
            Done
          </button>
        ) : (
          <>
            <button className="btn secondary" onClick={onClose}>
              Cancel
            </button>
            <button className="btn" disabled={busy || !name || !slug} onClick={submit}>
              {busy ? "Creating…" : "Create"}
            </button>
          </>
        )
      }
    >
      {done ? (
        <div className="notice green">
          Workspace <b>{done.slug}</b> created.
          <div className="small" style={{ marginTop: 8 }}>Service API key (shown once):</div>
          <div className="mono" style={{ wordBreak: "break-all" }}>{done.api_key}</div>
          {done.tempPw && (
            <>
              <div className="small" style={{ marginTop: 8 }}>
                First admin temporary password (shown once):
              </div>
              <div className="mono">{done.tempPw}</div>
            </>
          )}
        </div>
      ) : (
        <>
          <div className="form-group">
            <label>Company name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Technologies" />
          </div>
          <div className="form-group">
            <label>Slug</label>
            <input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="acme-technologies" />
          </div>
          <div className="form-group">
            <label>First admin email (optional)</label>
            <input
              value={adminEmail}
              onChange={(e) => setAdminEmail(e.target.value)}
              placeholder="admin@acme.com — provisioned as tenant_admin"
            />
          </div>
          <label className="small">Entitlements</label>
          <div className="chips" style={{ marginTop: 6 }}>
            {ENTITLEMENTS.map((e) => (
              <label key={e} className="chip" style={{ cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={ents.includes(e)}
                  onChange={() => toggle(e)}
                  style={{ marginRight: 6 }}
                />
                {e}
              </label>
            ))}
          </div>
        </>
      )}
    </Modal>
  );
}

function ManageModal({
  detail,
  onClose,
  onSaved,
  toast,
}: {
  detail: TenantDetail;
  onClose: () => void;
  onSaved: () => void;
  toast: Toast;
}) {
  const [name, setName] = useState(detail.name);
  const [ents, setEnts] = useState<string[]>(
    Object.entries(detail.entitlements).filter(([, v]) => v).map(([k]) => k),
  );
  const [busy, setBusy] = useState(false);

  const toggle = (e: string) =>
    setEnts((s) => (s.includes(e) ? s.filter((x) => x !== e) : [...s, e]));

  async function save() {
    setBusy(true);
    try {
      await updateTenant(detail.slug, { name: name.trim(), entitlements: ents });
      toast("Workspace updated", "success");
      onSaved();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      title={`Manage ${detail.slug}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn" disabled={busy} onClick={save}>
            {busy ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      {detail.status === "suspended" && (
        <div className="notice amber" style={{ marginBottom: 12 }}>
          Suspended{detail.suspended_at ? ` on ${fmtDate(detail.suspended_at)}` : ""}
          {detail.suspended_reason ? ` — ${detail.suspended_reason}` : ""}.
        </div>
      )}
      <div className="form-group">
        <label>Company name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <label className="small">Entitlements</label>
      <div className="chips" style={{ margin: "6px 0 12px" }}>
        {ENTITLEMENTS.map((e) => (
          <label key={e} className="chip" style={{ cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={ents.includes(e)}
              onChange={() => toggle(e)}
              style={{ marginRight: 6 }}
            />
            {e}
          </label>
        ))}
      </div>
      <div className="small muted">
        {Object.entries(detail.counts)
          .map(([k, v]) => `${v} ${k}`)
          .join(" · ")}
      </div>
      <div className="mono small muted" style={{ marginTop: 8, wordBreak: "break-all" }}>
        API key: {detail.api_key}
      </div>
    </Modal>
  );
}
