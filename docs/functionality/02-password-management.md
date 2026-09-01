# Password management

> Now also: **self-service forgot/reset** (`/api/auth/password/{forgot,reset}`,
> emailed 1-hour link), **reuse history** (`AUTH_PW_HISTORY`), optional
> **character-class rules** (`AUTH_PW_REQUIRE_*`) and an optional **Have I Been
> Pwned** breach check (`AUTH_PW_BREACH_CHECK`). See [`../AUTHENTICATION.md`](../AUTHENTICATION.md) §3.

## What it does

Lets users change their own password, lets admins reset someone else's, enforces
a password policy, and forces a change on first login for bootstrapped or
admin-created accounts.

## How it works

- **Policy** (`validate_password_policy`): minimum length `PASSWORD_MIN_LENGTH`
  (default 10) and the password may not equal the email address.
- **Self-service change** requires the current password. On success it
  re-hashes, bumps `password_version` (invalidating all JWTs), clears
  `force_password_change`, and revokes every refresh token — all sessions are
  signed out.
- **Admin reset** generates a one-time temporary password (`Kd-<random>`),
  returned once in the response, sets `force_password_change=1`, clears failed
  logins / lockout, and revokes the target's refresh tokens.
- **Forced change**: `force_password_change=1` accounts are redirected to
  `/change-password` and cannot use the rest of the app until they set a new
  password. The superadmin and every admin-created user start in this state.

## Interfaces

| Method | Path | Who |
|--------|------|-----|
| POST | `/api/auth/change-password` | the signed-in user |
| POST | `/api/users/{id}/reset-password` | user manager |

UI: `/change-password`.

## Permissions

- Self change: any signed-in user (not API keys — they have no password).
- Reset another user: `user.manage` (tenant_admin within own workspace,
  superadmin anywhere).

## Configuration

`PASSWORD_MIN_LENGTH`, `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD`.

## Source

- [`backend/app/security.py`](../../backend/app/security.py) — `hash_password`, `validate_password_policy`
- [`backend/app/routers/auth_routes.py`](../../backend/app/routers/auth_routes.py) — `change_password`
- [`backend/app/routers/users.py`](../../backend/app/routers/users.py) — `reset_password`

## Related

[Authentication](01-authentication.md) · [User management](06-user-management.md)
