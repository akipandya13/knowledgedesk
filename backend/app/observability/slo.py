"""Response-time targets (SLOs) computed from the live metric registry.

Each target names a latency histogram already collected by the app, a p95
budget from config, and whether the current window is within it. Surfaced at
``GET /api/observability/slo`` and, so it is alertable, as gauges
``slo.target.seconds{slo}`` / ``slo.p95.seconds{slo}`` / ``slo.compliant{slo}``
refreshed by the background probe.
"""
from __future__ import annotations

from ..config import get_settings
from . import gauge
from .registry import DEFAULT_BUCKETS

# slo name → (histogram metric, config attr for the p95 budget in ms, label filter)
_TARGETS = [
    ("api", "http.server.duration.seconds", "slo_api_p95_ms",
     lambda labels: not (labels.get("route") or "").startswith(
         ("/api/query/ask", "/api/query/search"))),
    ("rag_answer", "rag.answer.seconds", "slo_rag_answer_p95_ms", None),
    ("ingest_document", "ingest.document.seconds", "slo_ingest_doc_p95_ms", None),
]


def _quantile(series: list[dict], q: float) -> float | None:
    total = sum(s.get("count", 0) for s in series)
    if not total:
        return None
    merged: dict[float, float] = {}
    for s in series:
        for k, v in (s.get("buckets") or {}).items():
            merged[float(k)] = merged.get(float(k), 0) + v
    want = q * total
    for b in sorted(merged):
        if merged[b] >= want:
            return b
    bounds = sorted(merged) or list(DEFAULT_BUCKETS)
    return bounds[-1] if bounds else None


def slo_report(*, emit: bool = False) -> dict:
    from . import snapshot                       # local import — avoids a cycle at import time
    s = get_settings()
    metrics = {m["name"]: m for m in snapshot().get("metrics", [])}
    out = []
    all_ok = True
    for name, metric_name, attr, flt in _TARGETS:
        target_ms = getattr(s, attr)
        m = metrics.get(metric_name)
        series = m["series"] if m else []
        if flt is not None:
            series = [x for x in series if flt(x.get("labels", {}))]
        p50 = _quantile(series, 0.50)
        p95 = _quantile(series, 0.95)
        samples = sum(x.get("count", 0) for x in series)
        met = p95 is None or (p95 * 1000.0) <= target_ms
        if samples and not met:
            all_ok = False
        row = {"name": name, "metric": metric_name, "target_p95_ms": target_ms,
               "p50_ms": round(p50 * 1000, 1) if p50 is not None else None,
               "p95_ms": round(p95 * 1000, 1) if p95 is not None else None,
               "samples": int(samples), "met": bool(met)}
        out.append(row)
        if emit:
            try:
                gauge("slo.target.seconds", target_ms / 1000.0, slo=name,
                      help="Configured p95 latency budget")
                if p95 is not None:
                    gauge("slo.p95.seconds", p95, slo=name)
                gauge("slo.compliant", 1 if met else 0, slo=name,
                      help="1 = current p95 within the target")
            except Exception:                    # pragma: no cover
                pass
    return {"ok": all_ok, "targets": out}
