# Security event logging

## What it does

Records every security-relevant event on two complementary channels: an
**audit log** (the tamper-evident compliance record of *effected* changes) and
the **observability event stream** (the operational feed, including *attempts*
and denials) that ships to your SIEM.

## Channels

| | Audit log | Observability events |
|--|-----------|----------------------|
| Store | `audit_log` table, `detail` **encrypted at rest** | sinks: stdout (JSON), sqlite, webhook, OTLP … |
| Read | `GET /api/admin/audit` (`audit.read`), `GET /api/admin/platform/audit` (superadmin) | `GET /api/observability/events?kind=` (`observability.read`), or your sink |
| Scope | tenant / platform | tenant-scoped for non-superadmin |

## What is logged

**Authentication** — `auth.login`, `auth.login.failed` (+ `reason`, `locked`),
`auth.logins` counters by outcome, `auth.token.rejected` (bad/expired token,
disabled account, bad API key — with `reason`), `auth.session.timed_out`
(`idle`/`absolute`), `auth.session.evicted`, `auth.session.revoked[_all]`,
`auth.refresh.reuse_detected`, `auth.mfa.enabled|disabled|failed|recovery_used`,
`auth.sso.start`, `auth.password.changed|reset|reset_requested|expired`,
`auth.email.verified`.

**Authorization** — `authz.denied` (every `require()` / resource-ACL denial, with
the missing `permission`, `role`, `actor`, `tenant`, `route`) + an
`authz.denied` counter.

**Administration** — `user.*`, `tenant.*`, `access.*` (roles, groups, grants,
API keys, SSO, auth-policy), connector CRUD + sync, `doc.delete`, settings
changes.

## Password expiry (opt-in)

`AUTH_PW_MAX_AGE_DAYS` (default `0` = off; NIST 800-63B advises against forced
rotation, so it is disabled by default). When set, a login with a password older
than the limit flags `force_password_change` (sign-in still succeeds; the user is
sent to `/change-password`) and emits `auth.password.expired`.
`User.password_changed_at` tracks the last change.

## Interfaces

Read APIs above. No new endpoint — denials and rejections flow through the
existing observability pipeline.

## Permissions

`audit.read` (workspace audit), `platform.read` (platform audit),
`observability.read` (event stream).

## Source

- [`backend/app/auth.py`](../../backend/app/auth.py) — `log_denied`, `_reject`
- [`backend/app/routers/auth_routes.py`](../../backend/app/routers/auth_routes.py) — password expiry
- [`backend/app/services/audit.py`](../../backend/app/services/audit.py), [`backend/app/observability/`](../../backend/app/observability/)
- [`backend/tests/test_security_events.py`](../../backend/tests/test_security_events.py)

## Related

[Audit log](33-audit-log.md) · [Observability](41-observability.md) ·
[Authentication](01-authentication.md) · [Password management](02-password-management.md)
