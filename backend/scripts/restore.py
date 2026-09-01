#!/usr/bin/env python
"""Restore a KnowledgeDesk backup produced by ``scripts/backup.py``.

    # stop the API first so nothing writes the DB mid-copy
    docker compose stop app
    docker compose run --rm app python -m scripts.restore --archive /data/backups/kd-backup-<ts>.tar.gz --yes
    docker compose start app

Safety:

  * verifies every file against the manifest SHA-256 before touching anything;
  * refuses to overwrite a **non-empty** database, or a key file whose contents
    differ, unless ``--force`` (overwriting the KEK when the current data was
    encrypted under a different one destroys it);
  * ``--skip-qdrant`` / ``--skip-keys`` to restore a subset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tarfile
import tempfile

import httpx

from app.config import get_settings


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _db_is_populated(path: str) -> bool:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    try:
        con = sqlite3.connect(path)
        n = con.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        con.close()
        return n > 0
    except Exception:                                       # pragma: no cover
        return True


def _same_file(a: str, b: str) -> bool:
    return os.path.exists(b) and _sha256(a) == _sha256(b)


def _restore_qdrant(staging: str, manifest: dict, base_url: str) -> int:
    done = 0
    with httpx.Client(base_url=base_url, timeout=300) as c:
        for rel, _meta in manifest["files"].items():
            if not rel.startswith("qdrant/"):
                continue
            name = os.path.basename(rel)[: -len(".snapshot")]
            path = os.path.join(staging, rel)
            with open(path, "rb") as f:
                r = c.post(f"/collections/{name}/snapshots/upload?priority=snapshot",
                           files={"snapshot": (os.path.basename(path), f, "application/octet-stream")})
            r.raise_for_status()
            done += 1
    return done


def main(argv: list[str]) -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--yes", action="store_true", help="required to write anything")
    ap.add_argument("--force", action="store_true",
                    help="overwrite a populated DB / differing key files")
    ap.add_argument("--skip-qdrant", action="store_true")
    ap.add_argument("--skip-keys", action="store_true")
    args = ap.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="kd-restore-") as staging:
        with tarfile.open(args.archive, "r:gz") as tar:
            tar.extractall(staging)                         # noqa: S202 - our own archive
        manifest = json.load(open(os.path.join(staging, "manifest.json")))

        # 1. Integrity
        bad = []
        for rel, meta in manifest["files"].items():
            fp = os.path.join(staging, rel)
            if not os.path.exists(fp) or _sha256(fp) != meta["sha256"]:
                bad.append(rel)
        if bad:
            print(f"ABORT: checksum mismatch / missing: {bad}", file=sys.stderr)
            return 2
        print(f"Manifest OK — {len(manifest['files'])} file(s), created {manifest['created_at']}")

        if not args.yes:
            print("Dry run OK. Re-run with --yes to write "
                  "(the app should be stopped first).")
            return 0

        # 2. Pre-flight guards
        db_target = os.path.join(s.data_dir, "knowledgedesk.db")
        if _db_is_populated(db_target) and not args.force:
            print(f"ABORT: {db_target} already has tables. Move it aside or pass --force.",
                  file=sys.stderr)
            return 2
        if not args.skip_keys:
            for kf in ("secret.key", "data.key"):
                src = os.path.join(staging, "keys", kf)
                dst = os.path.join(s.data_dir, kf)
                if os.path.exists(src) and os.path.exists(dst) and not _same_file(src, dst) and not args.force:
                    print(f"ABORT: {dst} differs from the backup. --force to overwrite "
                          f"(only safe if no data was encrypted under the current key).", file=sys.stderr)
                    return 2

        # 3. Apply
        os.makedirs(s.data_dir, exist_ok=True)
        # DB (also clear stale WAL/SHM so SQLite doesn't replay onto the new file)
        for suffix in ("", "-wal", "-shm"):
            p = db_target + suffix
            if os.path.exists(p):
                os.remove(p)
        with open(os.path.join(staging, "db", "knowledgedesk.db"), "rb") as a, open(db_target, "wb") as b:
            b.write(a.read())
        print(f"  restored {db_target}")

        if not args.skip_keys:
            for kf in ("secret.key", "data.key"):
                src = os.path.join(staging, "keys", kf)
                if os.path.exists(src):
                    with open(src, "rb") as a, open(os.path.join(s.data_dir, kf), "wb") as b:
                        b.write(a.read())
                    os.chmod(os.path.join(s.data_dir, kf), 0o600)
                    print(f"  restored {kf}")

        if not args.skip_qdrant:
            try:
                n = _restore_qdrant(staging, manifest, s.qdrant_url)
                print(f"  restored {n} Qdrant collection(s)")
            except Exception as exc:                        # noqa: BLE001
                print(f"WARNING: Qdrant restore failed ({exc}). DB is restored; "
                      f"re-run with --skip-keys once Qdrant is reachable.", file=sys.stderr)

        print("Restore complete. Start the app.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
