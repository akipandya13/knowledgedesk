# Multi-factor authentication (TOTP)

## What it does

Optional time-based one-time-password (TOTP) second factor for user sign-in,
with one-time recovery codes. A workspace can require it.

## How it works

- **Enrol**: `POST /api/auth/mfa/setup` returns a base32 secret + an
  `otpauth://` URI (add to Google Authenticator / 1Password / Authy).
  `POST /api/auth/mfa/enable {code}` verifies a live code, turns MFA on, and
  returns **10 recovery codes** (shown once, stored as SHA-256, single-use).
- **Login**: when MFA is on, `POST /api/auth/login` returns
  `{mfa_required: true, mfa_token}` (a 5-minute interim JWT — not a session).
  `POST /api/auth/login/mfa {mfa_token, code}` with a TOTP or recovery code
  completes sign-in.
- **Disable**: `POST /api/auth/mfa/disable {password | code}` — refused if the
  tenant policy `mfa_required` is on.
- Secret is Fernet-encrypted at rest.

## Interfaces

| Method | Path |
|--------|------|
| POST | `/api/auth/mfa/setup` · `/mfa/enable` · `/mfa/disable` · `/mfa/recovery-codes` |
| POST | `/api/auth/login/mfa` |
| PUT | `/api/access/auth-policy` `{mfa_required}` |

UI: **Security** page (`/security`) for enrolment; **Access control →
Authentication** for the workspace policy; the login page shows the code step.

## Permissions

Self-service for any user. `mfa_required` policy needs `access.manage`.

## Configuration

`AUTH_TOTP_ISSUER`, `AUTH_MFA_TOKEN_MINUTES`.

## Source

- [`backend/app/security.py`](../../backend/app/security.py) — `new_totp_secret`, `verify_totp`, `new_recovery_codes`, `create_mfa_token`
- [`backend/app/routers/auth_routes.py`](../../backend/app/routers/auth_routes.py)
- [`backend/tests/test_auth_hardening.py`](../../backend/tests/test_auth_hardening.py)

## Related

[Authentication](01-authentication.md) · [Session & API-key management](45-session-and-api-key-management.md) ·
[`../AUTHENTICATION.md`](../AUTHENTICATION.md)
