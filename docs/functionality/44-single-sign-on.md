# Single sign-on (OIDC)

## What it does

Lets users sign in through the workspace's identity provider (Google, Okta,
Microsoft Entra, Auth0, Keycloak, any OIDC). Just-in-time provisions users on
first login. **Gated by the `sso` subscription entitlement** — the framework is
always present; the feature turns on per plan.

## How it works

- **Config** (`SsoConnection`, one per tenant): `issuer`, `client_id`,
  Fernet-encrypted `client_secret`, `allowed_domains`, `default_role`,
  `is_active`. Managed at `/api/access/sso` (`GET/PUT/DELETE`, `access.manage`);
  `PUT` returns `402` if the tenant lacks the `sso` entitlement.
- **Flow** — OIDC authorization code + PKCE, signed one-time state:
  1. `GET /api/auth/sso/lookup?email=` — the login page checks whether SSO is
     available for that address' domain.
  2. `GET /api/auth/sso/start?workspace=<slug>` → 302 to the IdP.
  3. `GET /api/auth/sso/callback?code&state` → exchange code, verify the
     `id_token` against the IdP's JWKS, check `email_verified` + allowed domain,
     match or JIT-create the user, mint a session, 302 to
     `<frontend>/login/sso/complete#access&refresh` (the SPA adopts the tokens
     and clears the fragment).
- JIT users get `auth_provider="sso"`, `email_verified=1`, the connection's
  `default_role`, and are pinned to that tenant.

## Entitlement

`ENTITLEMENTS=sso` globally, or `tenant.settings_json.entitlements = ["sso"]`
per workspace. Not entitled → the Access-control UI shows an upgrade card;
`lookup` reports `available: false`; `start` returns `402`.

## Interfaces

| Method | Path |
|--------|------|
| GET | `/api/auth/sso/lookup` · `/start` · `/callback` |
| GET/PUT/DELETE | `/api/access/sso` |

Register `<origin>/api/auth/sso/callback` as the IdP redirect URI.

UI: **Access control → Authentication → Single sign-on**; the login page shows
"Sign in with <name>".

## Source

- [`backend/app/routers/sso.py`](../../backend/app/routers/sso.py)
- [`backend/app/authn.py`](../../backend/app/authn.py) — `oidc_*`, `entitlement_enabled`
- [`backend/app/routers/access.py`](../../backend/app/routers/access.py) — SSO config CRUD
- [`backend/tests/test_auth_hardening.py`](../../backend/tests/test_auth_hardening.py)

## Related

[Authentication](01-authentication.md) · [Roles & permissions](03-roles-and-permissions.md) ·
[`../AUTHENTICATION.md`](../AUTHENTICATION.md)
