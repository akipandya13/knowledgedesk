#!/usr/bin/env python
"""Apply the governance retention windows to the activity and audit logs.

Retention is **opt-in and manual** — nothing is deleted automatically, so a
compliance record is never lost to a background job. Run it from cron / a
maintenance window when you actually want old rows trimmed:

    docker compose exec app python -m scripts.purge_logs --dry-run
    docker compose exec app python -m scripts.purge_logs --yes

Windows come from settings:

  * ACTIVITY_RETENTION_DAYS (default 90) — the behavioural stream.
  * AUDIT_RETENTION_DAYS    (default 0 = keep forever) — the compliance record.
    Only trimmed when explicitly set > 0. Purging an audit prefix leaves a
    ``seq`` gap; ``verify_chain`` reports the remaining rows as ``truncated``
    (not tampered) and still verifies their linkage.

Override either window for a single run with --activity-days / --audit-days.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from app.config import get_settings
from app.database import ActivityLog, AuditLog, SessionLocal


def _cutoff(days: int) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)


def main(argv: list[str]) -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--activity-days", type=int, default=s.activity_retention_days)
    ap.add_argument("--audit-days", type=int, default=s.audit_retention_days)
    ap.add_argument("--dry-run", action="store_true", help="report counts, delete nothing")
    ap.add_argument("--yes", action="store_true", help="required to actually delete")
    args = ap.parse_args(argv)

    db = SessionLocal()
    try:
        plan: list[tuple[str, object, dt.datetime]] = []
        if args.activity_days and args.activity_days > 0:
            plan.append(("activity_log", ActivityLog, _cutoff(args.activity_days)))
        if args.audit_days and args.audit_days > 0:
            plan.append(("audit_log", AuditLog, _cutoff(args.audit_days)))

        if not plan:
            print("Nothing to do: activity-days=%s audit-days=%s "
                  "(0 = keep forever)." % (args.activity_days, args.audit_days))
            return 0

        total = 0
        for name, model, cutoff in plan:
            n = db.query(model).filter(model.created_at < cutoff).count()
            total += n
            print(f"{name}: {n} row(s) older than {cutoff.date().isoformat()} "
                  f"({'would delete' if args.dry_run or not args.yes else 'deleting'})")
            if args.yes and not args.dry_run and n:
                db.query(model).filter(model.created_at < cutoff).delete(
                    synchronize_session=False)
        if args.yes and not args.dry_run:
            db.commit()
            print(f"Done — {total} row(s) deleted.")
        else:
            print(f"Dry run — pass --yes to delete {total} row(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
