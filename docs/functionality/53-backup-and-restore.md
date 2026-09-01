# Backup & restore

## What it does

Two container-run scripts that capture a point-in-time backup of everything
needed to rebuild the deployment — the SQLite metadata DB, the encryption keys,
and the Qdrant vector collections — and reinstate it on a fresh host.

## How it works

- **`scripts/backup.py`** → `kd-backup-<UTC-timestamp>.tar.gz` containing
  `db/knowledgedesk.db` (a crash-consistent copy via SQLite's online backup API
  — no downtime), `keys/secret.key` + `keys/data.key` (when on disk),
  `qdrant/<collection>.snapshot` per `kd_*` collection (via the Qdrant REST
  snapshot API), and `manifest.json` with a SHA-256 for every file. If Qdrant is
  unreachable the archive is written anyway with a note.
- **`scripts/restore.py`** verifies every checksum against the manifest, then
  (with `--yes`) restores the DB file, the keys, and uploads the Qdrant
  snapshots. Refuses to overwrite a **populated** DB or a **differing** key file
  unless `--force`. `--skip-qdrant` / `--skip-keys` for partial restores. The
  app must be stopped first (the DB file is copied).

## Interfaces

| Command | Purpose |
|---------|---------|
| `docker compose exec app python -m scripts.backup [--out DIR] [--no-qdrant]` | write an archive (runs live) |
| `docker compose run --rm app python -m scripts.restore --archive PATH` | dry run — verify the manifest |
| `… --archive PATH --yes [--force] [--skip-qdrant] [--skip-keys]` | apply |

## Configuration

`BACKUP_DIR` (default `{DATA_DIR}/backups`). The archive contains the encryption
keys — store it off-box and treat it as a secret.

## Source

- [`backend/scripts/backup.py`](../../backend/scripts/backup.py)
- [`backend/scripts/restore.py`](../../backend/scripts/restore.py)
- [`docs/BACKUP_RESTORE.md`](../BACKUP_RESTORE.md) — full runbook + DR checklist

## Related

[Resilience & recovery](52-resilience-and-recovery.md) ·
[Encryption at rest](47-encryption-at-rest.md) · [Health checks](37-health-check.md)
