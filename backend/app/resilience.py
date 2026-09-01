"""Retry-with-backoff for transient failures.

A dependency-free helper used at the few edges where a blip should not become a
user-visible error: the vector store, remote embedding calls, and connector
HTTP. Exponential backoff with full jitter; the set of retryable exceptions is
passed in per call site so a deterministic error (bad request, auth) fails fast.

    from .resilience import retry_call, aretry_call

    hits = retry_call(lambda: client.query_points(...),
                      op="qdrant.search", retry_on=(ConnectionError, TimeoutError))

Every attempt past the first increments ``retry.attempts{op}``; a final failure
increments ``retry.exhausted{op}`` — so flakiness is visible in metrics even
when the call ultimately succeeds.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time

from .config import get_settings

log = logging.getLogger("knowledgedesk.resilience")


class RetryError(RuntimeError):
    """Raised when every attempt failed; ``__cause__`` is the last error."""


def _obs():
    try:
        from . import observability as obs
        return obs
    except Exception:                                    # pragma: no cover
        return None


def _delays(attempts: int, base: float, cap: float):
    for i in range(attempts - 1):
        yield min(cap, base * (2 ** i)) * (0.5 + random.random() / 2)


def _params(attempts, base_delay, max_delay):
    s = get_settings()
    return (
        attempts or s.retry_max_attempts,
        (base_delay if base_delay is not None else s.retry_base_delay_ms / 1000.0),
        (max_delay if max_delay is not None else s.retry_max_delay_ms / 1000.0),
    )


def retry_call(fn, *, op: str, retry_on: tuple[type[BaseException], ...] = (Exception,),
               attempts: int | None = None, base_delay: float | None = None,
               max_delay: float | None = None):
    """Call ``fn()``; retry on ``retry_on`` with backoff. Returns fn's result or
    raises :class:`RetryError` (or the original error if it is not retryable)."""
    attempts, base_delay, max_delay = _params(attempts, base_delay, max_delay)
    obs = _obs()
    last: BaseException | None = None
    delays = list(_delays(attempts, base_delay, max_delay))
    for n in range(attempts):
        try:
            return fn()
        except retry_on as exc:                          # noqa: B902 - caller-scoped
            last = exc
            if n == attempts - 1:
                break
            if obs:
                obs.count("retry.attempts", op=op, help="Retried operations")
            log.warning("retry %s: attempt %d/%d failed (%s); backing off %.2fs",
                        op, n + 1, attempts, exc, delays[n])
            time.sleep(delays[n])
    if obs:
        obs.count("retry.exhausted", op=op, help="Operations that failed every attempt")
    raise RetryError(f"{op} failed after {attempts} attempts") from last


async def aretry_call(fn, *, op: str, retry_on: tuple[type[BaseException], ...] = (Exception,),
                      attempts: int | None = None, base_delay: float | None = None,
                      max_delay: float | None = None):
    """Async counterpart of :func:`retry_call` — ``fn`` is an async callable."""
    attempts, base_delay, max_delay = _params(attempts, base_delay, max_delay)
    obs = _obs()
    last: BaseException | None = None
    delays = list(_delays(attempts, base_delay, max_delay))
    for n in range(attempts):
        try:
            return await fn()
        except retry_on as exc:                          # noqa: B902
            last = exc
            if n == attempts - 1:
                break
            if obs:
                obs.count("retry.attempts", op=op)
            log.warning("retry %s: attempt %d/%d failed (%s); backing off %.2fs",
                        op, n + 1, attempts, exc, delays[n])
            await asyncio.sleep(delays[n])
    if obs:
        obs.count("retry.exhausted", op=op)
    raise RetryError(f"{op} failed after {attempts} attempts") from last
