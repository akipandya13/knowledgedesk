# KnowledgeDesk — Default Users and Passwords

Created automatically on **first startup, when the SQLite volume is empty**. One
account per role type. Sign in at `http://localhost:3000`.

| Role | Email / Key | Password | Scope |
|---|---|---|---|
| **superadmin** (platform) | `superadmin@knowledgedesk.local` | `Superadmin!Kd1` | Workspaces, cross-workspace users, platform audit/stats. **No** access to any workspace's documents or Q&A. |
| **tenant_admin** (workspace) | `admin@demo.knowledgedesk.local` | `TenantAdmin!Kd1` | Everything in the `demo` workspace: documents, users, settings, connectors, audit, access control, observability. |
| **member** (workspace) | `member@demo.knowledgedesk.local` | `Member!Kd1234` | Ask questions, manage own workspace documents, read the shared document list and insights, set up own 2FA. |
| **service** (API key) | `kd-demo-key` | — | `X-API-Key: kd-demo-key`. `tenant_admin`-level content access for the `demo` workspace; cannot manage users. |

Legacy `ADMIN_API_KEY=kd-admin-key` (`X-Admin-Key`) is **disabled** unless
`AUTH_LEGACY_ADMIN_KEY_ENABLED=true`. Use the superadmin login instead.

These values are the defaults in [`backend/app/config.py`](backend/app/config.py)
(`SUPERADMIN_*`, `DEMO_ADMIN_*`, `DEMO_MEMBER_*`, `DEMO_TENANT_API_KEY`) and can
be overridden in `.env` **before the first boot**.

## Notes

- None of these are prompted to change their password on first login (demo
  posture). Set `SUPERADMIN_FORCE_PASSWORD_CHANGE=true` to re-enable that for the
  platform account.
- Emails are pre-verified. 2FA (TOTP) is available per user at **Security**
  (`/security`); a workspace can require it under **Access control →
  Authentication**.
- Surrounding whitespace on a pasted password is trimmed, so a trailing space or
  newline from copy-paste is fine.

## Existing volume from an older build?

Bootstrap **only creates missing users** — it never rewrites an existing one.
If the table above doesn't work, your `app_data` volume was first created on an
older build with different defaults. Known historical sets:

| Build (≈commit) | superadmin | tenant_admin | member |
|---|---|---|---|
| **current** (`664b8ce`+) | `superadmin@knowledgedesk.local` / `Superadmin!Kd1` | `admin@demo.knowledgedesk.local` / `TenantAdmin!Kd1` | `member@demo.knowledgedesk.local` / `Member!Kd1234` |
| **early** (≤ `81cb4fd`) | `superadmin@knowledgedesk.local` / `ChangeMe!Now1` *(forced change on first login)* | `admin@demo.knowledgedesk.local` / `Demo-Admin123!` | `employee@demo.knowledgedesk.local` / `Demo-User123!` |

Check what your volume actually has:

```bash
docker compose exec app python -c "from app.database import SessionLocal,User; \
[print(u.email, u.role, 'force_change='+str(u.force_password_change)) for u in SessionLocal().query(User)]"
```

The simplest fix is a clean reset (below) — then the table at the top works
verbatim.

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
