# Session & API-key management

## What it does

Lets users see and revoke their own sign-in sessions, and lets admins issue,
name, expire and revoke multiple hashed API keys per workspace.

## Sessions

Each sign-in starts a refresh-token chain with `user_agent`, `ip`, `label`,
`session_started_at` (carried across single-use rotation), `created_at`,
`last_used_at`.

**Lifetime is enforced across rotation**, not per token:

| Control | Setting | Default |
|---------|---------|---------|
| Idle timeout — no refresh within the window ends the session | `AUTH_SESSION_IDLE_HOURS` | 72 |
| Absolute cap — a session cannot outlive this regardless of activity | `AUTH_SESSION_MAX_DAYS` | 30 |
| Concurrent cap — oldest chain evicted past this | `AUTH_MAX_SESSIONS_PER_USER` | 10 |

| Method | Path | |
|--------|------|--|
| GET | `/api/auth/sessions` | list; send `X-Refresh-Token` to get the `current` marker |
| DELETE | `/api/auth/sessions/{id}` | revoke one |
| DELETE | `/api/auth/sessions?keep_current=true` | revoke every *other* session |
| DELETE | `/api/auth/sessions` | revoke all |

Also revoked on password change/reset, account disable, logout, timeout, and
refresh-token reuse. Timeouts emit `auth.session.timed_out` /
`auth.session.evicted` observability events. UI: **Security** page (`/security`)
— shows "This device" and "Sign out other sessions".

## API keys (v2)

`ApiKey` — multiple **named** keys per workspace, **SHA-256 hashed at rest**,
optional `expires_at`, revocable, `last_used_at` tracked. The auth door checks
this table first, then falls back to the legacy single plaintext
`Tenant.api_key` (unchanged, still valid). A key authenticates as the `service`
role: tenant_admin-level content access, never `user.manage`.

| Method | Path | |
|--------|------|--|
| GET | `/api/access/api-keys` | list (prefix only, never the secret) |
| POST | `/api/access/api-keys` `{name, expires_in_days?}` | create — raw key returned once |
| DELETE | `/api/access/api-keys/{id}` | revoke |

UI: **Access control → Authentication → API keys**.

## Permissions

Sessions: self-service. API keys: `access.manage`.

## Source

- [`backend/app/database.py`](../../backend/app/database.py) — `ApiKey`, `RefreshToken` (+ metadata)
- [`backend/app/auth.py`](../../backend/app/auth.py) — `_resolve_api_key`
- [`backend/app/routers/auth_routes.py`](../../backend/app/routers/auth_routes.py) — sessions
- [`backend/app/routers/access.py`](../../backend/app/routers/access.py) — API-key CRUD
- [`backend/tests/test_auth_hardening.py`](../../backend/tests/test_auth_hardening.py)

## Related

[Authentication](01-authentication.md) · [API keys / service accounts](04-api-keys-and-service-accounts.md) ·
[Multi-factor authentication](43-multi-factor-authentication.md)
