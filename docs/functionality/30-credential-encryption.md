# Credential encryption

## What it does

Encrypts every third-party secret (AWS keys, Azure API keys, Google service
account JSON, SharePoint client secrets) at rest. Plaintext secrets never touch
the database and are never returned by the API.

## How it works

- A single **Fernet** master key from `KD_SECRET_KEY`. If unset, one is generated
  once and persisted to `DATA_DIR/secret.key` (0600). `KD_SECRET_KEY` may be a
  real Fernet key or an arbitrary passphrase (hashed to 32 bytes).
- `encrypt_secrets(dict)` → a single Fernet token stored in
  `ModelConnector.secret_encrypted` / `DataConnector.secret_encrypted`.
- `decrypt_secrets(token)` → dict, or `{}` on any tamper/format error.
- API responses expose only `secret_fields_set` — the **names** of the fields
  that have a value, e.g. `["api_key"]`.
- On update, sending `""` for a secret field clears it; omitting it leaves it
  unchanged; sending a value replaces it.

## Configuration

`KD_SECRET_KEY` — in production, inject from a KMS / secrets manager rather than
letting it fall back to a file.

## Source

- [`backend/app/crypto.py`](../../backend/app/crypto.py)
- [`backend/app/routers/admin.py`](../../backend/app/routers/admin.py) / [`connectors.py`](../../backend/app/routers/connectors.py) — `_connector_public` / `_public`

## Related

[Model connectors](26-model-connectors.md) · [Google Drive connector](13-google-drive-connector.md) ·
[SharePoint connector](14-sharepoint-connector.md)
