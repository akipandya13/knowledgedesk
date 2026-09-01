# Secrets management

One pluggable resolver ([`app/secret_resolver.py`](../backend/app/secret_resolver.py))
that every secret-consuming subsystem goes through, so a deployment can source
**all** of its secrets — config *and* stored connector credentials — from
whatever backend it mandates.

## Reference syntax

Anywhere a secret is expected, use a literal **or** a reference:

```
${provider:locator}
${provider:locator#key}          # provider returns JSON → pick a key
${provider:locator|fallback}     # use fallback if unresolved (empty allowed)
```

Resolution is cached for `SECRETS_CACHE_TTL` seconds (default 300). A reference
that can't be resolved and has no `|fallback` **raises** — fail closed.

## Providers

| Provider | Locator | Auth | Needs |
|----------|---------|------|-------|
| `env` | env var name | — | built-in |
| `file` | file path (`/run/secrets/…` for Docker/K8s) | — | built-in |
| `literal` | the value itself | — | built-in (escape hatch) |
| `vault` | `mount/path` (default mount `secret`), KV v2 | `VAULT_ADDR`, `VAULT_TOKEN` | `hvac` |
| `awssm` | secret id / ARN | default AWS credential chain | `boto3` (already a dep) |
| `gcpsm` | `projects/P/secrets/S[/versions/V]` | ADC / `GOOGLE_APPLICATION_CREDENTIALS` | `google-cloud-secret-manager` |
| `azkv` | `https://<vault>.vault.azure.net/secrets/<name>[/<ver>]` | `DefaultAzureCredential` | `azure-keyvault-secrets` + `azure-identity` |

`GET /api/access/secrets` (needs `access.manage`) lists the providers this
deployment can actually use; the **Access control → Authentication** page shows
them.

### Add your own

```python
from app import secret_resolver as sr
sr.PROVIDERS["mine"] = lambda locator: my_backend.fetch(locator)   # → str | None
```

## Where it's applied

| Secret | Resolved in |
|--------|-------------|
| **KEK** — `KD_SECRET_KEY` (each comma part) | `crypto._kek()` |
| **JWT secret** — `JWT_SECRET` | `security.jwt_secret()` |
| **SMTP password** — `SMTP_PASSWORD` | `authn.send_email()` |
| **Observability sink tokens** — `OBS_WEBHOOK_TOKEN`, `OBS_OTLP_HEADERS`, `OBS_PROMETHEUS_TOKEN` | sink builders |
| **Legacy admin key** — `ADMIN_API_KEY` | `auth.require_admin()` |
| **Bootstrap passwords** — `SUPERADMIN_PASSWORD`, `DEMO_ADMIN_PASSWORD`, `DEMO_MEMBER_PASSWORD` | `_bootstrap_db()` |
| **Stored connector / SSO secrets** (AWS/Azure keys, Google SA JSON, SharePoint & OIDC client secrets) | `crypto.decrypt_secrets(token, resolve=True)` — on the *runtime* path only (`tenant_settings._connector_overrides`, SSO callback); the admin UI keeps and displays the reference, never the resolved value |

So an admin can paste `${vault:secret/data/kd/bedrock#aws_secret_access_key}`
into a connector's secret field: it is Fernet-stored as that reference and
fetched from Vault each time the connector runs.

## Examples

```bash
# .env
KD_SECRET_KEY=${vault:secret/data/kd#kek}
JWT_SECRET=${file:/run/secrets/jwt_secret}
SMTP_PASSWORD=${awssm:kd/prod/smtp-password}
OBS_WEBHOOK_TOKEN=${env:SIEM_TOKEN|}
```

## Source

- [`backend/app/secret_resolver.py`](../backend/app/secret_resolver.py) — providers, `resolve_secret`, `resolve_mapping`
- [`backend/app/crypto.py`](../backend/app/crypto.py) — KEK + `decrypt_secrets(resolve=…)`
- [`backend/tests/test_secret_resolver.py`](../backend/tests/test_secret_resolver.py)
