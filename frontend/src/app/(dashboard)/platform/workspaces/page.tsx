"use client";

import { useCallback, useEffect, useState } from "react";
import { createTenant, deleteTenant, listTenants } from "@/lib/api/platform";
import type { TenantRow } from "@/lib/types";
import { Empty, Loading, PageHeader, TableWrap, fmtDate } from "@/components/ui";
import { Modal } from "@/components/Modal";
import { IconTrash } from "@/components/icons";
import { useToast } from "@/components/Toast";

export default function WorkspacesPage() {
  const { toast } = useToast();
  const [rows, setRows] = useState<TenantRow[] | null>(null);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [created, setCreated] = useState<{ slug: string; api_key: string } | null>(null);
  const [busy, setBusy] = useState(false);

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

  async function submit() {
    setBusy(true);
    try {
      const res = await createTenant(name.trim(), slug.trim().toLowerCase().replace(/\s+/g, "-"));
      setCreated({ slug: res.slug, api_key: res.api_key });
      toast("Workspace created", "success");
      setName("");
      setSlug("");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Create failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function remove(s: string) {
    if (!confirm(`Delete workspace "${s}" and ALL its users, documents and vectors? This cannot be undone.`))
      return;
    try {
      await deleteTenant(s);
      toast("Workspace deleted", "success");
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Delete failed", "error");
    }
  }

  if (!rows) return <Loading />;

  return (
    <>
      <PageHeader
        title="Workspaces"
        subtitle="Create and remove tenant workspaces."
        actions={
          <button
            className="btn"
            onClick={() => {
              setCreated(null);
              setOpen(true);
            }}
          >
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
              <th>Users</th>
              <th>Documents</th>
              <th>API key</th>
              <th>Created</th>
              <th />
            </>
          }
        >
          {rows.map((t) => (
            <tr key={t.id}>
              <td style={{ fontWeight: 600 }}>{t.name}</td>
              <td className="mono">{t.slug}</td>
              <td>{t.users}</td>
              <td>{t.documents}</td>
              <td className="mono small">{t.api_key}</td>
              <td className="small muted">{fmtDate(t.created_at)}</td>
              <td>
                <button className="btn danger sm" onClick={() => remove(t.slug)} aria-label="Delete">
                  <IconTrash />
                </button>
              </td>
            </tr>
          ))}
        </TableWrap>
      )}

      <Modal
        open={open}
        title="New workspace"
        onClose={() => setOpen(false)}
        footer={
          created ? (
            <button className="btn" onClick={() => setOpen(false)}>
              Done
            </button>
          ) : (
            <>
              <button className="btn secondary" onClick={() => setOpen(false)}>
                Cancel
              </button>
              <button className="btn" disabled={busy || !name || !slug} onClick={submit}>
                {busy ? "Creating…" : "Create"}
              </button>
            </>
          )
        }
      >
        {created ? (
          <div className="notice green">
            Workspace <b>{created.slug}</b> created. Service API key (shown once):
            <div className="mono" style={{ marginTop: 6 }}>
              {created.api_key}
            </div>
          </div>
        ) : (
          <>
            <div className="form-group">
              <label>Company name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Technologies" />
            </div>
            <div className="form-group">
              <label>Slug</label>
              <input
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="acme-technologies"
              />
            </div>
          </>
        )}
      </Modal>
    </>
  );
}
