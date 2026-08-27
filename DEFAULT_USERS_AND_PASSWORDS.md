# KnowledgeDesk v1 — Default Users and Passwords

These accounts are created automatically on first startup when the SQLite volume is empty.

| Role | Email / Key | Password | Notes |
|---|---|---|---|
| Platform superadmin | `superadmin@knowledgedesk.local` | `ChangeMe!Now1` | Must change password on first login. Manages workspaces/platform only; no tenant document access. |
| Demo tenant admin | `admin@demo.knowledgedesk.local` | `Demo-Admin123!` | Can upload documents, manage users, see audit, configure connectors, and change tenant model settings. |
| Demo employee/member | `employee@demo.knowledgedesk.local` | `Demo-User123!` | Can ask questions, view documents and insights. |
| Demo service API key | `kd-demo-key` | Not applicable | Use as `X-API-Key: kd-demo-key` for API demos and connector-style calls. |
| Legacy platform admin API key | `kd-admin-key` | Not applicable | Legacy script compatibility only. Prefer the superadmin UI login. Change before production. |

## Important

- Change these before any real deployment.
- Values come from `.env` for first boot. If Docker volumes already exist, changing `.env` will not rewrite existing users.
- To reset demo users from scratch, stop the stack and remove the `app_data` volume.
