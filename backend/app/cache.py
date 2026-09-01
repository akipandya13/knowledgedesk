"""Small in-process caches.

Not a distributed cache — a bounded, TTL'd dict that shaves repeated work off
the hot path (resolving a tenant's model config on every query, mostly). Safe
for a single-process or few-process deployment; multi-process just means each
worker warms its own copy, and the TTL bounds staleness.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable


class TTLCache:
    """Thread-safe, size-bounded, time-expiring key→value store."""

    def __init__(self, *, ttl: float, maxsize: int = 512):
        self._ttl = ttl
        self._maxsize = maxsize
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get_or_set(self, key: Any, factory: Callable[[], Any]) -> Any:
        if self._ttl <= 0:
            return factory()
        now = time.monotonic()
        with self._lock:
            hit = self._data.get(key)
            if hit is not None and now - hit[0] < self._ttl:
                self.hits += 1
                return hit[1]
        value = factory()                        # compute outside the lock
        with self._lock:
            if len(self._data) >= self._maxsize:
                # drop the oldest ~10% — cheap, good enough for this size
                for k in sorted(self._data, key=lambda k: self._data[k][0])[: self._maxsize // 10 + 1]:
                    self._data.pop(k, None)
            self._data[key] = (now, value)
            self.misses += 1
        return value

    def invalidate(self, predicate: Callable[[Any], bool] | None = None) -> int:
        with self._lock:
            if predicate is None:
                n = len(self._data)
                self._data.clear()
                return n
            drop = [k for k in self._data if predicate(k)]
            for k in drop:
                self._data.pop(k, None)
            return len(drop)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"size": len(self._data), "hits": self.hits, "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0}


# ── Tenant model-config cache ────────────────────────────────────
# resolve_model_config() runs on every RAG query and every ingest; when a model
# connector is selected it also opens a session and may resolve a ${secret:...}
# over the network. Cache the result keyed by tenant id + a hash of its
# settings_json, so any settings edit yields a fresh key automatically; the
# connector CRUD / settings handlers also invalidate explicitly for immediacy.

def _config_cache() -> TTLCache:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        from .config import get_settings
        _CONFIG_CACHE = TTLCache(ttl=get_settings().tenant_config_cache_ttl, maxsize=256)
    return _CONFIG_CACHE


_CONFIG_CACHE: TTLCache | None = None


def tenant_config_cache() -> TTLCache:
    return _config_cache()


def invalidate_tenant_config(tenant_id: int | None = None) -> None:
    cache = _config_cache()
    if tenant_id is None:
        cache.invalidate()
    else:
        cache.invalidate(lambda k: isinstance(k, tuple) and k[0] == tenant_id)
