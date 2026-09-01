#!/usr/bin/env python
"""Point-in-time backup of everything KnowledgeDesk needs to be restored.

    docker compose exec app python -m scripts.backup                 # → {BACKUP_DIR}/kd-backup-<ts>.tar.gz
    docker compose exec app python -m scripts.backup --out /data/backups
    docker compose exec app python -m scripts.backup --no-qdrant     # metadata + keys only

What goes in the archive:

  * db/knowledgedesk.db     — a *consistent* copy via SQLite's online backup API
                              (no need to stop the app)
  * keys/secret.key         — the KEK, if it lives on disk (not when KD_SECRET_KEY
  * keys/data.key             is set). WITHOUT THESE the encrypted columns,
                              connector secrets and Qdrant chunk text are
                              unrecoverable — guard them like a password.
  * qdrant/<collection>.snapshot — one Qdrant snapshot per tenant collection,
                              downloaded over the REST API.
  * manifest.json           — versions, timestamps, and a SHA-256 for every file.

Restore with ``scripts/restore.py``. See docs/BACKUP_RESTORE.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import tarfile
import tempfile

import httpx

from app.config import get_settings

_VERSION = 1


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _backup_sqlite(src: str, dst: str) -> None:
    """Online backup — a crash-consistent copy while the app keeps running."""
    con = sqlite3.connect(src)
    try:
        bck = sqlite3.connect(dst)
        with bck:
            con.backup(bck)
        bck.close()
    finally:
        con.close()


def _qdrant_snapshots(staging: str, base_url: str) -> list[dict]:
    out: list[dict] = []
    os.makedirs(os.path.join(staging, "qdrant"), exist_ok=True)
    with httpx.Client(base_url=base_url, timeout=120) as c:
        cols = c.get("/collections").json()["result"]["collections"]
        names = [x["name"] for x in cols if x["name"].startswith("kd_")]
        for name in names:
            snap = c.post(f"/collections/{name}/snapshots").json()["result"]["name"]
            r = c.get(f"/collections/{name}/snapshots/{snap}")
            r.raise_for_status()
            fn = os.path.join(staging, "qdrant", f"{name}.snapshot")
            with open(fn, "wb") as f:
                f.write(r.content)
            c.delete(f"/collections/{name}/snapshots/{snap}")   # don't leave it on the server
            out.append({"collection": name, "file": f"qdrant/{name}.snapshot"})
    return out


def main(argv: list[str]) -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=s.backup_dir or os.path.join(s.data_dir, "backups"))
    ap.add_argument("--no-qdrant", action="store_true", help="skip Qdrant snapshots")
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = os.path.join(args.out, f"kd-backup-{ts}.tar.gz")

    with tempfile.TemporaryDirectory(prefix="kd-backup-") as staging:
        files: dict[str, dict] = {}

        # 1. SQLite (consistent copy)
        os.makedirs(os.path.join(staging, "db"))
        db_src = os.path.join(s.data_dir, "knowledgedesk.db")
        db_dst = os.path.join(staging, "db", "knowledgedesk.db")
        _backup_sqlite(db_src, db_dst)
        files["db/knowledgedesk.db"] = {"sha256": _sha256(db_dst), "bytes": os.path.getsize(db_dst)}

        # 2. Keys (only if on disk)
        os.makedirs(os.path.join(staging, "keys"))
        key_notes = []
        for kf in ("secret.key", "data.key"):
            p = os.path.join(s.data_dir, kf)
            if os.path.exists(p):
                d = os.path.join(staging, "keys", kf)
                with open(p, "rb") as a, open(d, "wb") as b:
                    b.write(a.read())
                files[f"keys/{kf}"] = {"sha256": _sha256(d), "bytes": os.path.getsize(d)}
            elif kf == "secret.key":
                key_notes.append("secret.key not on disk (KD_SECRET_KEY is set) — "
                                 "back up that env value / KMS entry separately")

        # 3. Qdrant snapshots
        qdrant = []
        if not args.no_qdrant:
            try:
                qdrant = _qdrant_snapshots(staging, s.qdrant_url)
                for q in qdrant:
                    fp = os.path.join(staging, q["file"])
                    files[q["file"]] = {"sha256": _sha256(fp), "bytes": os.path.getsize(fp)}
            except Exception as exc:                        # noqa: BLE001
                key_notes.append(f"Qdrant snapshot failed ({exc}); archive has metadata only")
                print(f"WARNING: {key_notes[-1]}", file=sys.stderr)

        manifest = {
            "version": _VERSION,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "data_dir": s.data_dir,
            "qdrant": {"url": s.qdrant_url, "collections": [q["collection"] for q in qdrant]},
            "files": files,
            "notes": key_notes,
        }
        mpath = os.path.join(staging, "manifest.json")
        with open(mpath, "w") as f:
            json.dump(manifest, f, indent=2)

        with tarfile.open(archive, "w:gz") as tar:
            tar.add(mpath, arcname="manifest.json")
            for rel in files:
                tar.add(os.path.join(staging, rel), arcname=rel)

    size_mb = os.path.getsize(archive) / (1024 * 1024)
    print(f"Backup written: {archive} ({size_mb:.1f} MB)")
    print(f"  db + {len([f for f in manifest['files'] if f.startswith('keys/')])} key file(s)"
          f" + {len(qdrant)} Qdrant collection(s)")
    for n in key_notes:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
