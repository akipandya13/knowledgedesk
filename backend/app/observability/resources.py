"""Infrastructure / resource-utilization metrics.

A periodic collector that turns host + process state into gauges on the same
registry as every application metric — so CPU, memory, disk, file descriptors,
threads and GC show up in ``GET /metrics`` and the JSON snapshot next to
``http.server.*`` and ``rag.*``.

Design notes
------------
* **Best-effort, never fatal.** ``psutil`` is used when present (clean,
  cross-platform); each probe is guarded individually so one unavailable metric
  (a permission, a platform quirk) does not stop the rest, and the whole
  collector missing just means no resource gauges — nothing else breaks.
* **On a timer, not per request.** Started from ``app.main`` startup like the
  dependency probe (``OBS_RESOURCE_METRICS_SECONDS``); refreshing on an interval
  means monitoring sees saturation even when the app is idle.
* **Gauges only.** Point-in-time utilization; rates/deltas are Prometheus'
  job.
"""
from __future__ import annotations

import gc
import logging
import os
import time

from ..config import get_settings
from . import gauge

log = logging.getLogger("knowledgedesk.observability")

try:                                              # optional, but in requirements
    import psutil
    _PROC = psutil.Process(os.getpid())
except Exception:                                 # pragma: no cover - platform/deps
    psutil = None
    _PROC = None

_started = time.time()


def _safe(fn, metric: str) -> None:
    try:
        fn()
    except Exception:                             # pragma: no cover - defensive
        log.debug("resource metric %s unavailable", metric, exc_info=True)


def collect_resource_metrics() -> None:
    """Emit one round of process + system utilization gauges."""
    gauge("process.uptime.seconds", time.time() - _started,
          help="Seconds since the resource collector started")

    # ── Python runtime (always available) ────────────────────────
    _safe(lambda: gauge("python.gc.objects", len(gc.get_objects()),
                        help="Tracked objects on the GC heap"),
          "python.gc.objects")
    counts = gc.get_count()
    for i, c in enumerate(counts):
        _safe(lambda i=i, c=c: gauge("python.gc.collections", c, generation=str(i),
                                     help="Uncollected allocations per GC generation"),
              "python.gc.collections")
    _safe(lambda: gauge("process.threads", _thread_count(),
                        help="OS threads in this process"), "process.threads")

    if psutil is None or _PROC is None:
        return

    # ── Process ─────────────────────────────────────────────────
    _safe(lambda: gauge("process.cpu.percent", _PROC.cpu_percent(interval=None),
                        help="Process CPU utilization (%, one core = 100)"),
          "process.cpu.percent")
    _safe(lambda: gauge("process.memory.rss.bytes", (_mem()).rss,
                        help="Resident set size"), "process.memory.rss.bytes")
    _safe(lambda: gauge("process.memory.vms.bytes", (_mem()).vms,
                        help="Virtual memory size"), "process.memory.vms.bytes")
    _safe(lambda: gauge("process.memory.percent", _PROC.memory_percent(),
                        help="Process RSS as % of total system memory"),
          "process.memory.percent")
    _safe(lambda: gauge("process.open_fds", _PROC.num_fds(),
                        help="Open file descriptors"), "process.open_fds")

    # ── System / host ──────────────────────────────────────────
    _safe(lambda: gauge("system.cpu.percent", psutil.cpu_percent(interval=None),
                        help="Host CPU utilization (%)"), "system.cpu.percent")
    _safe(lambda: gauge("system.cpu.count", psutil.cpu_count() or 0,
                        help="Logical CPUs"), "system.cpu.count")
    vm = psutil.virtual_memory()
    _safe(lambda: gauge("system.memory.percent", vm.percent,
                        help="Host memory used (%)"), "system.memory.percent")
    _safe(lambda: gauge("system.memory.available.bytes", vm.available,
                        help="Host memory available"), "system.memory.available.bytes")
    _safe(_load_average, "system.load.average")
    _safe(_disk_usage, "system.disk")


def _thread_count() -> int:
    if _PROC is not None:
        try:
            return _PROC.num_threads()
        except Exception:                         # pragma: no cover
            pass
    import threading
    return threading.active_count()


def _mem():
    return _PROC.memory_info()


def _load_average() -> None:
    if not hasattr(os, "getloadavg"):
        return
    one, five, fifteen = os.getloadavg()
    gauge("system.load.average", one, window="1m", help="Run-queue load average")
    gauge("system.load.average", five, window="5m")
    gauge("system.load.average", fifteen, window="15m")


def _disk_usage() -> None:
    path = get_settings().data_dir if os.path.isdir(get_settings().data_dir) else "/"
    du = psutil.disk_usage(path)
    gauge("system.disk.percent", du.percent, path=path,
          help="Disk used at the data directory (%)")
    gauge("system.disk.free.bytes", du.free, path=path, help="Disk free bytes")


def resource_snapshot() -> dict:
    """A small dict view for the health endpoint / dashboard (independent of the
    registry so it works even with observability disabled)."""
    out: dict = {"threads": _thread_count(),
                 "gc_objects": None}
    try:
        out["gc_objects"] = len(gc.get_objects())
    except Exception:                             # pragma: no cover
        pass
    if psutil is None or _PROC is None:
        return out
    try:
        out["cpu_percent"] = _PROC.cpu_percent(interval=None)
        out["memory_rss_bytes"] = _PROC.memory_info().rss
        out["memory_percent"] = round(_PROC.memory_percent(), 2)
        out["open_fds"] = _PROC.num_fds()
        vm = psutil.virtual_memory()
        out["system_memory_percent"] = vm.percent
        out["system_cpu_percent"] = psutil.cpu_percent(interval=None)
    except Exception:                             # pragma: no cover
        pass
    return out


async def resource_metrics_loop(period: int) -> None:
    import asyncio
    while True:
        try:
            collect_resource_metrics()
        except Exception:                         # never let the collector die
            log.exception("resource metrics collection failed")
        await asyncio.sleep(period)
