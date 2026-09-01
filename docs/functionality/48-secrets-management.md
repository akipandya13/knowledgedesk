# Secrets management

## What it does

Lets every secret the platform uses — config values **and** stored connector /
SSO credentials — be sourced from an external store (env, files, HashiCorp
Vault, AWS/GCP/Azure secret managers) through one pluggable resolver, instead of
pasting literals.

## How it works

- A secret is a literal, or a reference:
  `${provider:locator[#jsonkey][|fallback]}`
  ([`app/secret_resolver.py`](../../backend/app/secret_resolver.py)).
- **Built-in providers** (no deps): `env`, `file` (`/run/secrets/…`), `literal`.
  **Optional** (enabled when the SDK is present): `vault` (hvac), `awssm`
  (boto3), `gcpsm`, `azkv`. Register more in `PROVIDERS`.
- Resolution is cached (`SECRETS_CACHE_TTL`, 300 s). Unresolvable + no fallback →
  raises (fail closed).
- Applied to: the KEK, JWT secret, SMTP password, observability sink tokens,
  legacy admin key, bootstrap passwords, and — on the runtime path only —
  decrypted connector / SSO secret bundles (`decrypt_secrets(resolve=True)`).
  The admin UI stores and shows the reference, never the resolved secret.

## Interfaces

`GET /api/access/secrets` (`access.manage`) — providers available in this
deployment + the reference syntax. Shown on **Access control → Authentication**;
connector modals hint the syntax on every secret field.

## Configuration

`SECRETS_CACHE_TTL`. Provider auth uses each backend's standard env
(`VAULT_ADDR`/`VAULT_TOKEN`, AWS chain, ADC, `DefaultAzureCredential`). Full
table + examples: [`../SECRETS_MANAGEMENT.md`](../SECRETS_MANAGEMENT.md).

## Source

- [`backend/app/secret_resolver.py`](../../backend/app/secret_resolver.py)
- [`backend/app/crypto.py`](../../backend/app/crypto.py) — `decrypt_secrets(resolve=…)`
- [`backend/tests/test_secret_resolver.py`](../../backend/tests/test_secret_resolver.py)

## Related

[Credential encryption](30-credential-encryption.md) · [Encryption at rest](47-encryption-at-rest.md) ·
[Model connectors](26-model-connectors.md) · [Single sign-on](44-single-sign-on.md)
