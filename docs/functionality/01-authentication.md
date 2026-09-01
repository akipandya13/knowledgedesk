# Authentication

> Extended since first written: **TOTP MFA** ([43](43-multi-factor-authentication.md)),
> **SSO/OIDC** ([44](44-single-sign-on.md)), **session + API-key management**
> ([45](45-session-and-api-key-management.md)), login rate-limiting, self-service
> password reset, email verification and a configurable password policy. Full
> reference: [`../AUTHENTICATION.md`](../AUTHENTICATION.md).

## What it does

Signs human users in and keeps them signed in, without ever storing a plaintext
password or a long-lived bearer token.

## How it works

- **Login** verifies the email + password (bcrypt) and returns a **token pair**:
  a short-lived **access JWT** (HS256, 30 min default) and an opaque
  **refresh token** (256-bit; only its SHA-256 hash is stored).
- Every API request is authorised **from the access token**, never from the
  request body. The JWT carries `sub` (user id), `role`, `tid`/`ten` (tenant),
  and `pwv` (password version). Changing a password bumps `pwv` and instantly
  invalidates every outstanding JWT for that user.
- **Refresh** is single-use rotation: each refresh issues a new pair and revokes
  the old refresh token. Re-presenting a already-revoked token is treated as
  theft — the entire token family for that user is revoked.
- **Logout** revokes the presented refresh token.
- The JWT signing secret comes from `JWT_SECRET` if set, otherwise it is
  generated once and persisted under `DATA_DIR/.jwt_secret` so restarts don't
  sign everyone out.
- **Account lockout**: after `LOGIN_MAX_FAILURES` (default 5) wrong passwords the
  account is locked for `LOGIN_LOCKOUT_MINUTES` (default 15). Login errors are
  identical for "unknown email" and "wrong password" — no account enumeration.

## Interfaces

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/auth/login` | email + password → token pair |
| POST | `/api/auth/refresh` | refresh token → new token pair |
| POST | `/api/auth/logout` | revoke a refresh token |
| GET  | `/api/auth/me` | current principal (user or API key) |

UI: `/login`. The web client stores tokens in `localStorage` and refreshes
transparently on 401 ([`frontend/src/lib/auth`](../../frontend/src/lib/auth)).

## Permissions

None — these endpoints establish identity. `/api/auth/me` and `/logout` require
any valid credential.

## Configuration

`JWT_SECRET`, `ACCESS_TOKEN_MINUTES`, `REFRESH_TOKEN_DAYS`,
`LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES`.

## Source

- [`backend/app/security.py`](../../backend/app/security.py) — hashing, JWT, refresh tokens, lockout math
- [`backend/app/routers/auth_routes.py`](../../backend/app/routers/auth_routes.py)
- [`backend/app/auth.py`](../../backend/app/auth.py) — `get_principal`

## Related

[Password management](02-password-management.md) ·
[API keys / service accounts](04-api-keys-and-service-accounts.md) ·
[Roles & permissions](03-roles-and-permissions.md)
