# Authentication

Password + JWT with refresh-token rotation, plus: TOTP MFA, self-service
password reset, email verification, per-user session management, hashed
multi-key API keys, login rate-limiting, a configurable password policy, and
**SSO (generic OIDC) gated behind a subscription entitlement**.

Everything below is on by default except SSO, the httpOnly-cookie mode, the
password-complexity rules, the breach check, and the (removed-by-default) legacy
`X-Admin-Key`.

---

## 1. Login flow

```
POST /api/auth/login {email, password}
  ├─ rate limit (ip, ip+email sliding window) ................ 429 if exceeded
  ├─ generic 401 for unknown email OR wrong password
  ├─ account lockout after N failures ....................... 423
  ├─ tenant requires verified email & not verified .......... 403
  ├─ user has MFA  → { mfa_required: true, mfa_token }        (5-min interim JWT)
  └─ else          → { access_token, refresh_token, user }

POST /api/auth/login/mfa {mfa_token, code}
  └─ TOTP code OR a single-use recovery code → session
```

- **Access token** — HS256 JWT, 30 min. Claims `sub/role/tid/ten/pwv`.
- **Refresh token** — opaque 256-bit, only its SHA-256 hash stored, single-use
  rotation, reuse ⇒ whole-family revoke. Now also stores `user_agent`, `ip`,
  `label`, `last_used_at` for the sessions view.
- `pwv` (password version) still invalidates every access token on password
  change / reset.
- Optional `AUTH_REFRESH_COOKIE=true` also sets the refresh token as an
  httpOnly, SameSite=Lax cookie (`/api/auth` path). Requires explicit
  `CORS_ALLOW_ORIGINS`.

## 2. TOTP multi-factor

| Endpoint | |
|----------|--|
| `POST /api/auth/mfa/setup` | returns `secret` + `otpauth://` URI (not yet enabled) |
| `POST /api/auth/mfa/enable` `{code}` | verifies a live code → enables → returns 10 one-time **recovery codes** (shown once) |
| `POST /api/auth/mfa/disable` `{password\|code}` | blocked if the tenant sets `mfa_required` |
| `POST /api/auth/mfa/recovery-codes` | regenerate (invalidates the old set) |

Secret is Fernet-encrypted at rest (`crypto`). Recovery codes stored as SHA-256,
consumed on use. Tenant policy: `POST /api/access/auth-policy {mfa_required}`.

UI: **Security** page (`/security`).

## 3. Password: policy, history, reset

- `validate_password_policy` — min length + optional upper/lower/digit/symbol
  (`AUTH_PW_REQUIRE_*`), reuse of the last `AUTH_PW_HISTORY` (default 5) hashes,
  and — opt-in — Have I Been Pwned via the keyless k-anonymity range API
  (`AUTH_PW_BREACH_CHECK=true`; fails open on network error).
- **Change** (`/api/auth/change-password`) — needs current password; records the
  old hash in `password_history`; revokes all sessions.
- **Forgot** (`/api/auth/password/forgot`) — always 200 (no enumeration);
  emails a 1-hour reset link.
- **Reset** (`/api/auth/password/reset {token, new_password}`) — single-use
  token; also marks the email verified.

## 4. Email verification

`users.email_verified` (existing + admin-created accounts default **verified**;
SSO-provisioned = verified). `POST /api/auth/email/verify {token}` (3-day link),
`POST /api/auth/email/resend`. Enforced at login only when the tenant sets
`require_verified_email`.

Delivery is pluggable — `EMAIL_SENDER = console | smtp | noop`. `console` (the
default) logs the link so it works with zero config; `smtp` uses
`SMTP_*`. Swap in a hosted provider by adding a branch to `authn.send_email`.

## 5. Sessions

`GET /api/auth/sessions` lists the caller's live refresh tokens (device, ip,
started, last used). `DELETE /api/auth/sessions/{id}` revokes one;
`DELETE /api/auth/sessions` revokes all. UI: **Security** page.

## 6. API keys (v2)

`ApiKey` table — **multiple named keys per workspace, hashed at rest
(SHA-256), optional expiry, revocable, `last_used_at` tracked**. The auth door
tries this table first, then falls back to the legacy single plaintext
`Tenant.api_key` (still works). Admin: `GET/POST /api/access/api-keys`,
`DELETE /api/access/api-keys/{id}` (raw key shown once). A key resolves to the
`service` role — tenant_admin-level content access, never `user.manage`.

## 7. Login rate limiting

In-process sliding window (`authn.login_limiter`): `AUTH_LOGIN_RATE_PER_MIN` per
`(ip,email)` and `AUTH_LOGIN_RATE_IP_PER_MIN` per ip. Returns `429`. Complements
the per-account lockout (which still applies). For multi-instance deployments,
front with a WAF/edge rate limiter.

## 8. SSO — generic OIDC (subscription: `sso`)

Framework built in; **the feature is gated by the `sso` entitlement**
(`ENTITLEMENTS=sso` globally, or `tenant.settings_json.entitlements = ["sso"]`).
Not entitled → config `PUT` returns `402`, the login page shows SSO as an
upgrade.

Per-tenant `SsoConnection`: `issuer`, `client_id`, encrypted `client_secret`,
`allowed_domains`, `default_role`, `is_active`. Works with any OIDC provider
(Google, Okta, Microsoft Entra, Auth0, Keycloak).

```
GET /api/auth/sso/lookup?email=  → login page asks "SSO for this address?"
GET /api/auth/sso/start?workspace=<slug>   → 302 to the IdP (auth-code + PKCE, signed state)
GET /api/auth/sso/callback?code&state      → verify id_token (JWKS), check email domain,
                                             JIT-provision or match user, mint session,
                                             302 → <frontend>/login/sso/complete#access&refresh
```

Register `<origin>/api/auth/sso/callback` as the redirect URI with the IdP.
Admin UI: **Access control → Authentication → Single sign-on**.

## 9. Config reference

See `.env.example` (`AUTH_*`, `EMAIL_*`, `SMTP_*`, `CORS_ALLOW_ORIGINS`,
`ENTITLEMENTS`). Legacy `X-Admin-Key` is disabled unless
`AUTH_LEGACY_ADMIN_KEY_ENABLED=true`.

## 10. Source

- [`backend/app/security.py`](../backend/app/security.py) — TOTP, recovery codes, email tokens, api-key hashing, policy + HIBP
- [`backend/app/authn.py`](../backend/app/authn.py) — rate limiter, email sender, entitlements, OIDC client
- [`backend/app/routers/auth_routes.py`](../backend/app/routers/auth_routes.py) — login/MFA/reset/verify/sessions
- [`backend/app/routers/sso.py`](../backend/app/routers/sso.py) — OIDC flow
- [`backend/app/routers/access.py`](../backend/app/routers/access.py) — auth-policy, API keys, SSO config
- [`backend/app/auth.py`](../backend/app/auth.py) — auth door (ApiKey lookup), legacy-key gate
- [`backend/tests/test_auth_hardening.py`](../backend/tests/test_auth_hardening.py) — 12 tests
- frontend: `login`, `forgot-password`, `reset-password`, `verify-email`,
  `login/sso/complete`, `(dashboard)/security`, `(dashboard)/access` → Authentication tab
