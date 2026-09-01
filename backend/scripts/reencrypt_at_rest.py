#!/usr/bin/env python
"""Convert legacy plaintext at rest to ciphertext, and re-wrap the data key after
a KEK rotation.

Run inside the app container:

    docker compose exec app python -m scripts.reencrypt_at_rest          # encrypt legacy rows + vectors
    docker compose exec app python -m scripts.reencrypt_at_rest --rewrap # after changing KD_SECRET_KEY

Encryption is transparent for *new* writes the moment the code is deployed; this
only backfills data that predates it. Safe to run repeatedly (idempotent).
"""
from __future__ import annotations

import sys

from app import crypto
from app.database import AuditLog, QueryLog, SessionLocal
from app.services import vectorstore


def rewrap() -> None:
    crypto.rewrap_data_key()
    print("data.key re-wrapped under the current primary KD_SECRET_KEY.")


def backfill_db() -> None:
    db = SessionLocal()
    try:
        n = 0
        for row in db.query(QueryLog).yield_per(200):
            # reading decrypts (or passes through legacy); reassigning re-encrypts on flush
            row.question, row.answer, row.sources_json = row.question, row.answer, row.sources_json
            n += 1
        for row in db.query(AuditLog).yield_per(500):
            row.detail = row.detail
        db.commit()
        print(f"query_log + audit_log: {n} query rows rewritten (encrypted at rest).")
    finally:
        db.close()


def backfill_vectors() -> None:
    tally = vectorstore.reencrypt_text_payloads()
    if tally:
        for name, count in tally.items():
            print(f"  {name}: {count} chunk payloads encrypted")
    else:
        print("vectors: nothing to do (all encrypted or no collections).")


def main(argv: list[str]) -> int:
    if "--rewrap" in argv:
        rewrap()
        return 0
    backfill_db()
    backfill_vectors()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
