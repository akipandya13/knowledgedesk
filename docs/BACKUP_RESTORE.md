# Backup & restore

Two scripts, run inside the `app` container, that capture and reinstate
everything KnowledgeDesk needs: the SQLite metadata DB, the encryption keys, and
the Qdrant vector collections.

## What's in a backup

| Path in archive | What | Notes |
|-----------------|------|-------|
| `db/knowledgedesk.db` | all metadata (tenants, users, documents, roles, audit, activity, …) | copied via SQLite's **online backup API** — crash-consistent, no downtime |
| `keys/secret.key` | the KEK | only present when it lives on disk (absent when `KD_SECRET_KEY` / a KMS supplies it — back that up separately) |
| `keys/data.key` | the wrapped DEK | **without the keys the encrypted columns, connector secrets and Qdrant chunk text are unrecoverable** |
| `qdrant/<collection>.snapshot` | one Qdrant snapshot per `kd_*` collection | downloaded over the REST API; skipped (with a note) if Qdrant is unreachable |
| `manifest.json` | version, timestamp, and a SHA-256 for every file | verified on restore before anything is written |

## Backup

```bash
docker compose exec app python -m scripts.backup
#   → {BACKUP_DIR or /data/backups}/kd-backup-<UTC-timestamp>.tar.gz

docker compose exec app python -m scripts.backup --out /data/backups
docker compose exec app python -m scripts.backup --no-qdrant     # metadata + keys only
```

Runs against the live app. Schedule it with cron / a sidecar; copy the archive
**off the box** (it contains the keys — treat it like a password vault).

## Restore

Restore copies the DB file, so **stop the API first**:

```bash
docker compose stop app

# dry run — verifies the manifest checksums, writes nothing
docker compose run --rm app python -m scripts.restore --archive /data/backups/kd-backup-<ts>.tar.gz

# apply
docker compose run --rm app python -m scripts.restore --archive /data/backups/kd-backup-<ts>.tar.gz --yes

docker compose start app
```

Guards (override with `--force`):

- refuses to overwrite a **populated** database — move the existing
  `knowledgedesk.db` aside first, or `--force`;
- refuses to overwrite a key file whose contents **differ** from the backup —
  replacing the KEK when the current data was encrypted under a different one
  destroys it.

Partial restores: `--skip-qdrant` (DB + keys only) · `--skip-keys` (when the KEK
comes from the environment). If the Qdrant upload fails the DB restore still
completes and the script tells you to re-run `--skip-keys` once Qdrant is back.

## Disaster-recovery checklist

1. Fresh host, `docker compose up -d` (creates empty volumes).
2. `docker compose stop app`.
3. `restore --archive <latest> --yes` (`--force` if the empty boot already
   created tables).
4. `docker compose start app`; check `GET /readyz` → `200`.

## Source

- [`backend/scripts/backup.py`](../backend/scripts/backup.py)
- [`backend/scripts/restore.py`](../backend/scripts/restore.py)
- [`docs/ENCRYPTION_AT_REST.md`](ENCRYPTION_AT_REST.md) — why the keys matter
- [`docs/RESILIENCE.md`](RESILIENCE.md)
