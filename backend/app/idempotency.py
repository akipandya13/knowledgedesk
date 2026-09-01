"""Idempotency for mutating requests.

A client that retries a ``POST`` / ``PUT`` / ``PATCH`` / ``DELETE`` after a
timeout or a dropped connection risks acting twice. If it sends a stable
``Idempotency-Key`` header, this middleware makes the retry safe: the first
request runs and its response is stored; a retry with the same key replays that
stored response instead of re-executing the handler.

Semantics (Stripe-style):

* key seen, same method+path+body  → replay the stored status + body
* key seen, **different body**      → ``409`` (a key must identify one request)
* key seen, still ``in_progress``   → ``409`` (a retry raced the original)
* handler raised / 5xx             → the in-progress row is dropped so the
  client may legitimately retry
* no header, or feature disabled   → passthrough, nothing stored

Identity is taken from the bearer JWT claims (no DB) or a single API-key
lookup, so the key namespace is per principal and cannot collide across
workspaces. Responses are stored encrypted (they can contain workspace data)
and pruned after ``IDEMPOTENCY_TTL_HOURS`` by the startup reconciler.
"""
from __future__ import annotations

import hashlib
import logging

from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import get_settings
from .database import IdempotencyKey, SessionLocal
from .security import decode_access_token, hash_api_key

log = logging.getLogger("knowledgedesk.idempotency")

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_MAX_CACHED_BODY = 256 * 1024


def _scope_for(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        payload = decode_access_token(auth[7:].strip())
        if payload:
            return f"t{payload.get('tid')}:u{payload.get('sub')}"
    raw = (request.headers.get("x-api-key") or request.headers.get("x-tenant-key") or "").strip()
    if raw:
        db = SessionLocal()
        try:
            from .database import ApiKey
            row = (db.query(ApiKey)
                   .filter(ApiKey.key_hash == hash_api_key(raw), ApiKey.revoked == 0)
                   .first())
            if row:
                return f"t{row.tenant_id}:k{row.prefix}"
        finally:
            db.close()
    return None


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        key = request.headers.get("idempotency-key", "").strip()
        if (not s.idempotency_enabled or not key
                or request.method not in _MUTATING
                or not request.url.path.startswith("/api/")):
            return await call_next(request)

        scope = _scope_for(request)
        if scope is None:                       # unauthenticated → let auth 401 it
            return await call_next(request)

        body = await request.body()
        fp = hashlib.sha256(body).hexdigest()
        path = request.url.path

        db = SessionLocal()
        try:
            row = (db.query(IdempotencyKey)
                   .filter(IdempotencyKey.scope == scope, IdempotencyKey.key == key)
                   .first())
            if row is not None:
                if row.in_progress:
                    return _conflict("A request with this Idempotency-Key is already in progress")
                if row.method != request.method or row.path != path or row.request_fingerprint != fp:
                    return _conflict("Idempotency-Key was already used for a different request")
                _count("replayed")
                return JSONResponse(status_code=row.status_code or 200,
                                    content=_loads(row.response_body),
                                    headers={"Idempotency-Replayed": "true"})
            try:
                db.add(IdempotencyKey(scope=scope, key=key, method=request.method,
                                      path=path, request_fingerprint=fp, in_progress=True))
                db.commit()
            except IntegrityError:              # concurrent first request won the insert
                db.rollback()
                return _conflict("A request with this Idempotency-Key is already in progress")
        finally:
            db.close()

        # Run the handler, capturing the response so a retry can replay it.
        try:
            response = await call_next(request)
        except Exception:
            _discard(scope, key)
            raise

        response, raw_body = await _buffer(response)
        cacheable = (response.status_code < 500
                     and len(raw_body) <= _MAX_CACHED_BODY
                     and "text/event-stream" not in response.headers.get("content-type", ""))
        if cacheable:
            _finalize(scope, key, response.status_code, raw_body)
            _count("stored")
        else:
            _discard(scope, key)               # let the client retry a failed/oversized call
        return response


# ── helpers ──────────────────────────────────────────────────────

def _conflict(detail: str) -> JSONResponse:
    _count("conflict")
    return JSONResponse(status_code=409, content={"detail": detail})


def _count(outcome: str) -> None:
    try:
        from . import observability as obs
        obs.count("idempotency.requests", outcome=outcome, help="Idempotency-Key outcomes")
    except Exception:                           # pragma: no cover
        pass


async def _buffer(response: Response) -> tuple[Response, bytes]:
    chunks = [chunk async for chunk in response.body_iterator]
    raw = b"".join(
        c if isinstance(c, (bytes, bytearray)) else str(c).encode() for c in chunks)
    rebuilt = Response(content=raw, status_code=response.status_code,
                       headers=dict(response.headers), media_type=response.media_type)
    return rebuilt, raw


def _loads(text: str):
    import json
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {}


def _finalize(scope: str, key: str, status_code: int, raw_body: bytes) -> None:
    db = SessionLocal()
    try:
        row = (db.query(IdempotencyKey)
               .filter(IdempotencyKey.scope == scope, IdempotencyKey.key == key).first())
        if row is not None:
            row.status_code = status_code
            row.response_body = raw_body.decode("utf-8", "replace")
            row.in_progress = False
            db.commit()
    except Exception:                           # pragma: no cover
        db.rollback()
        log.exception("idempotency finalize failed")
    finally:
        db.close()


def _discard(scope: str, key: str) -> None:
    db = SessionLocal()
    try:
        db.query(IdempotencyKey).filter(
            IdempotencyKey.scope == scope, IdempotencyKey.key == key,
            IdempotencyKey.in_progress == True).delete()  # noqa: E712
        db.commit()
    except Exception:                           # pragma: no cover
        db.rollback()
    finally:
        db.close()
