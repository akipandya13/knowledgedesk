"""Audit trail — the tamper-evident compliance record of who did what, when.

Written for every security-relevant event that *effected* a change: logins
(success and failure), user & tenant lifecycle, access-control changes,
connector CRUD, settings changes, document upload and deletion. Read by
workspace admins (own workspace) and the platform operator (all).

Design notes
------------
* **Append-only + hash-chained.** Each row carries a per-workspace sequence
  number and ``entry_hash = SHA-256(canonical(row) || prev_hash)``. Editing or
  deleting any row makes every later row fail :func:`verify_chain`. The chain is
  keyed by ``tenant_id`` (platform-level events, ``tenant_id IS NULL``, share
  chain key ``0``).
* **Serialised.** A process-wide lock guards "read last row → compute hash →
  insert" so concurrent requests cannot fork a chain. Fine for the single
  SQLite writer this app uses; a multi-writer deployment would move this to a
  DB sequence + row lock.
* **Never breaks the request path.** A failed write is logged and swallowed —
  losing an audit row must not 500 a user action.
* **Encrypted at rest.** ``detail`` and ``meta`` use the DEK column types; the
  hash is computed over the *plaintext* so verification is stable across key
  rotation. Filter keys (action, actor_email, target_*) stay plaintext.
* **Data-modification history.** Pass ``changes={field: [old, new]}`` (build it
  with :func:`diff`) and it is stored in ``meta["changes"]`` — so it is both
  encrypted at rest and covered by the hash. Filtering the log by
  ``target_type`` + ``target_id`` then yields a tamper-evident change timeline
  for any entity (``GET /api/admin/audit/history``).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import threading

from ..database import AuditLog, utcnow
from ..request_context import current as _req

log = logging.getLogger("knowledgedesk.audit")

_chain_lock = threading.Lock()


def _ts_key(value) -> str:
    """Timestamp form the hash commits to. Normalised to naive-UTC, whole
    seconds, so it is identical whether ``value`` is the tz-aware datetime we
    just built or the (often naive) datetime SQLite hands back on read."""
    if value.tzinfo is not None:
        value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat()


#: Substrings that mark a field as sensitive — its values are masked in a
#: change-set (the fact that it changed is still recorded).
_REDACT_HINTS = ("password", "secret", "token", "api_key", "client_secret",
                 "private_key", "credential")


def _is_secret(field: str) -> bool:
    f = field.lower()
    return any(h in f for h in _REDACT_HINTS)


def diff(before: dict | None, after: dict | None, *, fields=None,
         redact=()) -> dict:
    """``{field: [old, new]}`` for every key whose value changed.

    ``fields`` restricts the comparison to that set; ``redact`` names extra
    fields to mask (secret-looking names are masked automatically). A masked
    change is recorded as ``["***", "***"]`` so the timeline shows *that* a
    secret rotated without leaking it.
    """
    before, after = before or {}, after or {}
    keys = set(fields) if fields is not None else (set(before) | set(after))
    out: dict = {}
    for k in keys:
        b, a = before.get(k), after.get(k)
        if b == a:
            continue
        if k in redact or _is_secret(k):
            out[k] = ["***", "***"]
        else:
            out[k] = [b, a]
    return out


def _summarize_changes(changes: dict) -> str:
    parts = []
    for field, pair in list(changes.items())[:12]:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            parts.append(f"{field}: {pair[0]!r} → {pair[1]!r}")
        else:
            parts.append(str(field))
    return "; ".join(parts)


def _chain_key(tenant_id: int | None) -> int:
    return int(tenant_id) if tenant_id is not None else 0


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _entry_hash(prev_hash: str, payload: dict) -> str:
    h = hashlib.sha256()
    h.update(prev_hash.encode("utf-8"))
    h.update(_canonical(payload).encode("utf-8"))
    return h.hexdigest()


def _hash_payload(row_like: dict) -> dict:
    """The subset of a row that the hash commits to — stable field order via
    ``_canonical``'s ``sort_keys``."""
    return {
        "seq": row_like["seq"],
        "tenant_id": row_like["tenant_id"],
        "actor_email": row_like["actor_email"],
        "actor_user_id": row_like["actor_user_id"],
        "actor_role": row_like["actor_role"],
        "action": row_like["action"],
        "target_type": row_like["target_type"],
        "target_id": row_like["target_id"],
        "detail": row_like["detail"],
        "meta": row_like["meta"] or {},
        "created_at": _ts_key(row_like["created_at"]),
    }


def record(db, *, action: str, actor_email: str = "", actor_role: str = "",
           tenant_id: int | None = None, detail: str = "",
           actor_user_id: int | None = None, target_type: str = "",
           target_id: "str | int" = "", meta: dict | None = None,
           changes: dict | None = None, principal=None) -> None:
    """Append one row to the audit chain. Best-effort; never raises.

    Pass ``principal=`` to fill actor_email / actor_role / actor_user_id /
    tenant_id from the request identity (explicit kwargs still win). Pass
    ``changes={field: [old, new]}`` (see :func:`diff`) to attach a
    data-modification history entry — it is folded into ``meta`` and, if
    ``detail`` is empty, summarised into it.
    """
    try:
        meta = dict(meta or {})
        if principal is not None:
            actor_email = actor_email or getattr(principal, "actor_label", "") \
                or getattr(principal, "email", "")
            actor_role = actor_role or getattr(principal, "role", "")
            if actor_user_id is None:
                actor_user_id = getattr(principal, "user_id", None)
            if tenant_id is None and getattr(principal, "tenant", None) is not None:
                tenant_id = principal.tenant.id
            akid = getattr(principal, "api_key_id", None)
            if akid is not None:
                meta.setdefault("api_key_id", akid)
                meta.setdefault("api_key_name", getattr(principal, "api_key_name", ""))
        if changes:
            meta["changes"] = changes
            if not detail:
                detail = _summarize_changes(changes)

        rc = _req()
        key = _chain_key(tenant_id)
        created_at = utcnow()

        with _chain_lock:
            last = (db.query(AuditLog)
                    .filter(AuditLog.tenant_id == tenant_id
                            if tenant_id is not None else AuditLog.tenant_id.is_(None))
                    .order_by(AuditLog.seq.desc(), AuditLog.id.desc())
                    .first())
            seq = (last.seq or 0) + 1 if last else 1
            prev_hash = (last.entry_hash if last else "") or ""

            row_like = {
                "seq": seq, "tenant_id": tenant_id,
                "actor_email": actor_email or "", "actor_user_id": actor_user_id,
                "actor_role": actor_role or "", "action": action,
                "target_type": target_type or "",
                "target_id": str(target_id) if target_id not in (None, "") else "",
                "detail": (detail or "")[:2000], "meta": meta or {},
                "created_at": created_at,
            }
            entry_hash = _entry_hash(prev_hash, _hash_payload(row_like))

            db.add(AuditLog(
                seq=seq, tenant_id=tenant_id, actor_email=row_like["actor_email"],
                actor_user_id=actor_user_id, actor_role=row_like["actor_role"],
                action=action, target_type=row_like["target_type"],
                target_id=row_like["target_id"], detail=row_like["detail"],
                meta=meta or {}, ip=rc.ip, user_agent=rc.user_agent,
                request_id=rc.request_id, created_at=created_at,
                prev_hash=prev_hash, entry_hash=entry_hash))
            db.commit()
    except Exception:                                     # noqa: BLE001
        db.rollback()
        log.exception("Audit write failed for action=%s", action)


# ── Read side ──────────────────────────────────────────────────────

def serialize(row: AuditLog) -> dict:
    return {
        "id": row.id, "seq": row.seq, "tenant_id": row.tenant_id,
        "actor": row.actor_email, "actor_user_id": row.actor_user_id,
        "actor_role": row.actor_role, "action": row.action,
        "target_type": row.target_type or None, "target_id": row.target_id or None,
        "detail": row.detail, "meta": row.meta or {},
        "changes": (row.meta or {}).get("changes") or None,
        "ip": row.ip or None, "request_id": row.request_id or None,
        "entry_hash": row.entry_hash or None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_entries(db, *, tenant_id: int | None = None, platform_all: bool = False,
                 action: str | None = None, action_prefix: str | None = None,
                 actor: str | None = None, target_type: str | None = None,
                 target_id: str | None = None, since=None, until=None,
                 before_id: int | None = None, limit: int = 100):
    """Filtered, newest-first slice of the audit log.

    ``platform_all`` (superadmin) spans every workspace; otherwise the query is
    pinned to ``tenant_id``. Cursor with ``before_id`` (pass the last ``id`` seen).
    """
    q = db.query(AuditLog)
    if not platform_all:
        q = q.filter(AuditLog.tenant_id == tenant_id)
    if action:
        q = q.filter(AuditLog.action == action)
    if action_prefix:
        q = q.filter(AuditLog.action.like(f"{action_prefix}%"))
    if actor:
        q = q.filter(AuditLog.actor_email.like(f"%{actor}%"))
    if target_type:
        q = q.filter(AuditLog.target_type == target_type)
    if target_id:
        q = q.filter(AuditLog.target_id == str(target_id))
    if since is not None:
        q = q.filter(AuditLog.created_at >= since)
    if until is not None:
        q = q.filter(AuditLog.created_at <= until)
    if before_id is not None:
        q = q.filter(AuditLog.id < before_id)
    return (q.order_by(AuditLog.id.desc())
            .limit(max(1, min(limit, 1000))).all())


def verify_chain(db, *, tenant_id: int | None = None, platform_all: bool = False) -> dict:
    """Recompute every hash and check linkage.

    Returns ``{ok, checked, unchained, truncated, chains: [...], first_broken}``.
    ``unchained`` counts pre-upgrade rows with no hash; ``truncated`` is set when
    a retention purge has removed a chain's prefix (``seq`` gap) — that is not a
    tamper failure. ``first_broken`` names the first row whose recomputed hash or
    predecessor link does not match.
    """
    q = db.query(AuditLog)
    if not platform_all:
        q = q.filter(AuditLog.tenant_id == tenant_id)
    rows = q.order_by(AuditLog.tenant_id, AuditLog.seq, AuditLog.id).all()

    chains: dict[int, list[AuditLog]] = {}
    for r in rows:
        chains.setdefault(_chain_key(r.tenant_id), []).append(r)

    summary = {"ok": True, "checked": 0, "unchained": 0, "truncated": False,
               "chains": [], "first_broken": None}

    for key, crows in sorted(chains.items()):
        prev_hash = ""
        prev_seq = None
        c_ok = True
        c_truncated = False
        c_checked = 0
        for r in crows:
            if not r.entry_hash:
                summary["unchained"] += 1
                continue
            if prev_seq is None:
                if (r.seq or 0) > 1:
                    c_truncated = summary["truncated"] = True
                prev_hash = r.prev_hash or ""           # anchor: trust the first link
            else:
                if (r.seq or 0) != prev_seq + 1:
                    c_truncated = summary["truncated"] = True
                if (r.prev_hash or "") != prev_hash:
                    c_ok = summary["ok"] = False
                    summary["first_broken"] = summary["first_broken"] or {
                        "id": r.id, "seq": r.seq, "tenant_id": r.tenant_id,
                        "reason": "prev_hash does not match the preceding entry"}
            expected = _entry_hash(r.prev_hash or "", _hash_payload({
                "seq": r.seq, "tenant_id": r.tenant_id, "actor_email": r.actor_email or "",
                "actor_user_id": r.actor_user_id, "actor_role": r.actor_role or "",
                "action": r.action, "target_type": r.target_type or "",
                "target_id": r.target_id or "", "detail": r.detail or "",
                "meta": r.meta or {}, "created_at": r.created_at,
            }))
            if expected != r.entry_hash:
                c_ok = summary["ok"] = False
                summary["first_broken"] = summary["first_broken"] or {
                    "id": r.id, "seq": r.seq, "tenant_id": r.tenant_id,
                    "reason": "entry_hash does not match the row contents"}
            prev_hash = r.entry_hash
            prev_seq = r.seq
            c_checked += 1
            summary["checked"] += 1
        summary["chains"].append({
            "chain_key": key, "entries": c_checked, "ok": c_ok,
            "truncated": c_truncated,
        })
    return summary
