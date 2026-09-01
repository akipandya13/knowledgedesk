"""Shared, connection-pooled outbound HTTP.

Every LLM generation, remote-embedding batch and connector call used to build a
fresh ``httpx.Client`` — a new TCP + TLS handshake per request. These two
module-level clients keep a warm connection pool
(``HTTP_POOL_MAX_KEEPALIVE`` / ``HTTP_POOL_MAX_CONNECTIONS``) so repeated calls
to the same host reuse a connection.

Timeouts stay per call: pass ``timeout=`` to ``get`` / ``post`` / ``stream`` —
it overrides the client default for that request. Closed on app shutdown
(``main.shutdown``); recreated lazily if used again after that (tests, scripts).
"""
from __future__ import annotations

import threading

import httpx

from .config import get_settings

_lock = threading.Lock()
_sync: httpx.Client | None = None
_async: httpx.AsyncClient | None = None


def _limits() -> httpx.Limits:
    s = get_settings()
    return httpx.Limits(max_connections=s.http_pool_max_connections,
                        max_keepalive_connections=s.http_pool_max_keepalive)


def get_client() -> httpx.Client:
    global _sync
    with _lock:
        if _sync is None or _sync.is_closed:
            _sync = httpx.Client(timeout=30.0, limits=_limits(), follow_redirects=True)
        return _sync


def get_async_client() -> httpx.AsyncClient:
    global _async
    with _lock:
        if _async is None or _async.is_closed:
            _async = httpx.AsyncClient(timeout=30.0, limits=_limits(), follow_redirects=True)
        return _async


def close() -> None:
    """Close the sync client (call from a sync shutdown hook)."""
    global _sync
    with _lock:
        c, _sync = _sync, None
    if c is not None and not c.is_closed:
        try:
            c.close()
        except Exception:                        # pragma: no cover - best effort
            pass


async def aclose() -> None:
    """Close the async client (call from an async shutdown hook)."""
    global _async
    with _lock:
        c, _async = _async, None
    if c is not None and not c.is_closed:
        try:
            await c.aclose()
        except Exception:                        # pragma: no cover
            pass
