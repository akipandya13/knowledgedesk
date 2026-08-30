"""Prometheus exposition.

This sink stores nothing itself — the always-on metric registry already holds
everything. Enabling it flips on the ``GET /metrics`` route
(see ``app.routers.observability``), which renders the registry in Prometheus
text format on each scrape. Optionally protect it with ``OBS_PROMETHEUS_TOKEN``.
"""
from __future__ import annotations

from .base import Sink


class PrometheusSink(Sink):
    name = "prometheus"

    def __init__(self, *, path: str = "/metrics", token: str = ""):
        self.path = path
        self.token = token
