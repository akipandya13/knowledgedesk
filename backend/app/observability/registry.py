"""In-process metric aggregation.

Always on when observability is enabled, independent of any sink. It powers
`GET /metrics` (Prometheus text) and `GET /api/observability/metrics` (JSON),
so the platform is observable with zero external tooling.

Aggregation is intentionally simple and bounded:
  * counter   — monotonic sum per label set
  * gauge     — last value per label set
  * histogram — fixed buckets + sum + count per label set

A per-metric series cap (`max_series`) protects memory against accidental
high-cardinality labels; overflow is counted in `observability_series_dropped_total`.
"""
from __future__ import annotations

import threading
import time

from .models import MetricKind, Sample

DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _key(labels: dict[str, str]) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in labels.items() if v is not None))


class _Metric:
    __slots__ = ("name", "kind", "help", "buckets", "series")

    def __init__(self, name: str, kind: MetricKind, help_: str, buckets):
        self.name = name
        self.kind = kind
        self.help = help_
        self.buckets = buckets or DEFAULT_BUCKETS
        # key -> dict(value=..., count=..., sum=..., buckets={upper: count})
        self.series: dict[tuple, dict] = {}


class Registry:
    def __init__(self, max_series: int = 2000):
        self._lock = threading.Lock()
        self._metrics: dict[str, _Metric] = {}
        self._max_series = max_series
        self._dropped = 0
        self._started = time.time()

    # ── ingest ────────────────────────────────────────────────────
    def record(self, s: Sample, *, help_: str = "", buckets=None) -> None:
        with self._lock:
            m = self._metrics.get(s.name)
            if m is None:
                m = _Metric(s.name, s.kind, help_, buckets)
                self._metrics[s.name] = m
            key = _key(s.labels)
            row = m.series.get(key)
            if row is None:
                if len(m.series) >= self._max_series:
                    self._dropped += 1
                    return
                row = {"value": 0.0, "count": 0, "sum": 0.0,
                       "buckets": {b: 0 for b in m.buckets}}
                m.series[key] = row
            if s.kind is MetricKind.COUNTER:
                row["value"] += s.value
            elif s.kind is MetricKind.GAUGE:
                row["value"] = s.value
            else:  # histogram
                row["count"] += 1
                row["sum"] += s.value
                for b in m.buckets:
                    if s.value <= b:
                        row["buckets"][b] += 1

    # ── read ──────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            out = []
            for m in self._metrics.values():
                series = []
                for key, row in m.series.items():
                    labels = {k: v for k, v in key}
                    entry = {"labels": labels}
                    if m.kind is MetricKind.HISTOGRAM:
                        entry.update(count=row["count"], sum=row["sum"],
                                     buckets={str(k): v for k, v in row["buckets"].items()})
                    else:
                        entry["value"] = row["value"]
                    series.append(entry)
                out.append({"name": m.name, "type": m.kind.value,
                            "help": m.help, "series": series})
            return {"uptime_seconds": time.time() - self._started,
                    "series_dropped": self._dropped, "metrics": out}

    def render_prometheus(self) -> str:
        with self._lock:
            lines: list[str] = []
            for m in self._metrics.values():
                pname = _prom_name(m.name)
                if m.help:
                    lines.append(f"# HELP {pname} {m.help}")
                lines.append(f"# TYPE {pname} {m.kind.value}")
                for key, row in m.series.items():
                    lbl = dict(key)
                    if m.kind is MetricKind.HISTOGRAM:
                        cum = 0
                        for b in m.buckets:
                            cum = row["buckets"][b]
                            lines.append(f'{pname}_bucket{_lbls(lbl, le=_num(b))} {cum}')
                        lines.append(f'{pname}_bucket{_lbls(lbl, le="+Inf")} {row["count"]}')
                        lines.append(f'{pname}_sum{_lbls(lbl)} {row["sum"]}')
                        lines.append(f'{pname}_count{_lbls(lbl)} {row["count"]}')
                    else:
                        lines.append(f'{pname}{_lbls(lbl)} {row["value"]}')
            return "\n".join(lines) + "\n"


def _prom_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in ":_" else "_" for c in name)


def _num(b: float) -> str:
    return f"{b:g}"


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _lbls(labels: dict, **extra) -> str:
    merged = {**labels, **extra}
    if not merged:
        return ""
    inner = ",".join(f'{_prom_name(k)}="{_esc(str(v))}"' for k, v in sorted(merged.items()))
    return "{" + inner + "}"
