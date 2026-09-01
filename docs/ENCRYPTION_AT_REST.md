# Encryption at rest

Layered, textbook model. Two layers are application-managed (this repo); the
outermost layer is infrastructure you must provide.

```
 ┌─ host / volume encryption ─────────────────────────────  (LUKS, EBS/PD, dm-crypt) — REQUIRED, infra
 │  ┌─ database-at-rest encryption ────────────────────────  (SQLCipher / Postgres TDE) — RECOMMENDED, infra
 │  │  ┌─ application envelope encryption ─────────────────  (this repo)
 │  │  │     KEK  ── wraps ──►  DEK  ── encrypts ──►  fields / payloads
 │  │  │     KD_SECRET_KEY      data.key              AES-128-CBC + HMAC (Fernet)
```

## 1. Key hierarchy (`app/crypto.py`)

| Key | Where | Rotation |
|-----|-------|----------|
| **KEK** | `KD_SECRET_KEY` (a Fernet key or passphrase). Blank → generated to `{DATA_DIR}/secret.key` (0600). **Production: from a KMS / Vault.** | `KD_SECRET_KEY="NEW,OLD"` — a `MultiFernet`: the first key encrypts, every key decrypts. |
| **DEK** | random Fernet key, stored **wrapped by the KEK** in `{DATA_DIR}/data.key` (0600). Generated on first use. | KEK rotation only **re-wraps** `data.key` — no data is re-encrypted. |

`encrypt()` / `decrypt()` use the DEK; ciphertext is tagged `kdenc:` so legacy
plaintext is read through unchanged (gradual rollout).

## 2. What is encrypted

| Data | Mechanism |
|------|-----------|
| **Q&A transcript** — `query_log.question`, `.answer`, `.sources_json` | `EncryptedText` / `EncryptedJSON` column types (DEK) |
| **Audit detail** — `audit_log.detail` | `EncryptedText` (DEK) |
| **Document content** — chunk `text` in every Qdrant payload | `encrypt()` on upsert, `decrypt()` on search (DEK) |
| **Observability** — `obs_events.fields_json`, `obs_spans.attributes_json` | `encrypt()` in the sqlite sink (DEK) |
| **Connector credentials, TOTP secrets, SSO client secrets** | `encrypt_secrets()` — Fernet with the **KEK** directly |
| **Passwords** | bcrypt (hash, not encryption) |
| **Refresh tokens, API keys, recovery/email tokens** | SHA-256 (hash) |

**Deliberately not encrypted** (needed for lookups / filters, low sensitivity):
user email + name, tenant name/slug, document `filename` / `department` /
`confidentiality` / `tags` (queried in the document list and as Qdrant filters),
`query_log.filters_json`. The embedding **vectors** are not encrypted (they are
derived and required plaintext for similarity search — treat the Qdrant volume
as sensitive and rely on layers 1–2).

## 3. Migrating existing data

New writes are encrypted the moment the code is deployed. Backfill older rows and
vectors:

```bash
docker compose exec app python -m scripts.reencrypt_at_rest
```

Idempotent. It rewrites `query_log` / `audit_log` rows and encrypts legacy
plaintext chunk payloads in every `kd_*` Qdrant collection.

## 4. KEK rotation

```bash
# 1. add the new key in front, keep the old one
KD_SECRET_KEY="<new>,<current>"
docker compose up -d
# 2. re-wrap the data key under the new KEK
docker compose exec app python -m scripts.reencrypt_at_rest --rewrap
# 3. (optional) re-encrypt KEK-level secret bundles, then drop the old key
KD_SECRET_KEY="<new>"
docker compose up -d
```

## 5. Infrastructure layers (you provide)

- **Volume/disk encryption is mandatory.** The Docker volumes `app_data`
  (SQLite + key files), `qdrant_data` (vectors) and `ollama_data` must sit on an
  encrypted filesystem. Keep `KD_SECRET_KEY` **off that disk** (env from a
  secrets manager) so `data.key` alone is useless.
- **Database-at-rest**: for a hardened deployment run SQLite via **SQLCipher**
  (whole-file AES) or migrate to **Postgres with TDE**. The app's ORM layer is
  unchanged either way.
- Backups inherit the ciphertext; store the KEK separately.

## Source

- [`backend/app/crypto.py`](../backend/app/crypto.py) — KEK/DEK, `encrypt`/`decrypt`, `EncryptedText`/`EncryptedJSON`
- [`backend/app/database.py`](../backend/app/database.py) — encrypted columns
- [`backend/app/services/vectorstore.py`](../backend/app/services/vectorstore.py) — Qdrant payload encryption + `reencrypt_text_payloads`
- [`backend/scripts/reencrypt_at_rest.py`](../backend/scripts/reencrypt_at_rest.py)
- [`backend/tests/test_encryption_at_rest.py`](../backend/tests/test_encryption_at_rest.py)
