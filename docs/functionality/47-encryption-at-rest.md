# Encryption at rest

## What it does

Envelope encryption for the sensitive data KnowledgeDesk stores on disk: the
Q&A transcript, audit detail, document chunk text in the vector store,
observability payloads, and (already) connector / MFA / SSO secrets.

## How it works

- **Two-tier keys** ([`app/crypto.py`](../../backend/app/crypto.py)):
  a **KEK** from `KD_SECRET_KEY` (a `MultiFernet` — comma list for rotation)
  wraps a random **DEK** stored encrypted in `{DATA_DIR}/data.key`. Rotating the
  KEK only re-wraps that file; no data is re-encrypted.
- **Transparent columns**: `EncryptedText` / `EncryptedJSON` SQLAlchemy types on
  `query_log.question/answer/sources_json` and `audit_log.detail`.
- **Vector store**: chunk `text` is `encrypt()`-ed into the Qdrant payload on
  upsert and `decrypt()`-ed in search results (filters and vectors are untouched).
- **Observability**: the sqlite sink encrypts `fields_json` / `attributes_json`.
- **Legacy plaintext** is read through unchanged (`kdenc:` tag) — encryption
  rolls out gradually; `scripts/reencrypt_at_rest.py` backfills old rows/vectors.
- **Not encrypted** (lookups/filters): emails, names, filenames, department,
  confidentiality, tags; embedding vectors (derived, needed for search).

## Interfaces

Operational, no API. `docker compose exec app python -m scripts.reencrypt_at_rest`
(backfill) / `--rewrap` (after KEK rotation).

## Configuration

`KD_SECRET_KEY` (KEK; from a KMS in production). Full guide + the required
infrastructure layers (disk encryption, SQLCipher / Postgres TDE):
[`../ENCRYPTION_AT_REST.md`](../ENCRYPTION_AT_REST.md).

## Source

- [`backend/app/crypto.py`](../../backend/app/crypto.py), [`backend/app/database.py`](../../backend/app/database.py)
- [`backend/app/services/vectorstore.py`](../../backend/app/services/vectorstore.py), [`backend/app/observability/sinks/sqlite.py`](../../backend/app/observability/sinks/sqlite.py)
- [`backend/scripts/reencrypt_at_rest.py`](../../backend/scripts/reencrypt_at_rest.py), [`backend/tests/test_encryption_at_rest.py`](../../backend/tests/test_encryption_at_rest.py)

## Related

[Credential encryption](30-credential-encryption.md) · [TLS & reverse proxy](46-tls-and-reverse-proxy.md) ·
[Query history](32-query-history.md) · [Audit log](33-audit-log.md)
