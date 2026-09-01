# KnowledgeDesk — Default Users and Passwords

Created automatically on first startup (when the SQLite volume is empty). One
account per role type. **Sign in at `http://localhost:3000`.**

| Role type | Email / Key | Password | Scope |
|---|---|---|---|
| **superadmin** (platform) | `superadmin@knowledgedesk.local` | `Superadmin!Kd1` | Workspaces, cross-workspace users, platform audit/stats. **No** access to any workspace's documents or Q&A. |
| **tenant_admin** (workspace) | `admin@demo.knowledgedesk.local` | `TenantAdmin!Kd1` | Everything in the `demo` workspace: documents (company-wide + members'), users, settings, connectors, audit, access control, observability. |
| **member** (workspace) | `member@demo.knowledgedesk.local` | `Member!Kd1234` | Ask questions, manage own workspace documents, read the shared document list and insights, set up own 2FA. |
| **service** (API key) | `kd-demo-key` | — | `X-API-Key: kd-demo-key`. `tenant_admin`-level content access for the `demo` workspace; cannot manage users. |

Legacy: `ADMIN_API_KEY=kd-admin-key` (`X-Admin-Key`) is **disabled** unless
`AUTH_LEGACY_ADMIN_KEY_ENABLED=true`. Use the superadmin login instead.

## Notes

- None of these are prompted to change their password on first login (demo
  posture). Set `SUPERADMIN_FORCE_PASSWORD_CHANGE=true` to re-enable that for the
  platform account.
- Emails are pre-verified. 2FA (TOTP) is available per user at **Security**
  (`/security`); a workspace can require it under **Access control →
  Authentication**.
- All values come from `.env` / `backend/app/config.py` at first boot only —
  `SUPERADMIN_*`, `DEMO_ADMIN_*`, `DEMO_MEMBER_*`, `DEMO_TENANT_API_KEY`.
  Changing them does **not** rewrite users in an existing volume.

## Reset from scratch

```bash
docker compose down
docker volume rm knowledgedesk_app_data      # wipes users, documents metadata, audit
docker compose up -d
```

## Before any real deployment

Change every value above, enable `SUPERADMIN_FORCE_PASSWORD_CHANGE`, set a strong
`JWT_SECRET` / `KD_SECRET_KEY`, and set `DEMO_TENANT_ENABLED=false` /
`DEMO_USERS_ENABLED=false`.
