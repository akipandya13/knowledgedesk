"""Sink registry — the extension seam.

`SINK_BUILDERS` maps a name (as used in ``OBSERVABILITY_SINKS``) to a factory
``(settings) -> Sink``. To add your own backend:

    from .base import Sink

    class MySink(Sink):
        name = "mine"
        blocking = True                 # if it does network I/O
        def on_event(self, e): ...

    SINK_BUILDERS["mine"] = lambda s: MySink(url=s.obs_mine_url)

…then set ``OBSERVABILITY_SINKS=stdout,mine``. Nothing else changes.
"""
from __future__ import annotations

import logging
import os

from .base import Sink
from .mongodb import MongoSink
from .noop import NoopSink
from .otlp import OtlpSink
from .postgres import PostgresSink
from .prometheus import PrometheusSink
from .sqlite import SqliteSink
from .stdout import StdoutSink
from .webhook import WebhookSink

log = logging.getLogger("knowledgedesk.observability")


def _sec(v):
    from ...secret_resolver import resolve_secret
    return resolve_secret(v) or ""


def _sqlite_builder(s) -> Sink:
    path = getattr(s, "obs_sqlite_path", "") or os.path.join(s.data_dir, "observability.db")
    return SqliteSink(path=path, retention_hours=getattr(s, "obs_sqlite_retention_hours", 168))


SINK_BUILDERS: dict[str, callable] = {
    "noop": lambda s: NoopSink(),
    "stdout": lambda s: StdoutSink(pretty=getattr(s, "obs_stdout_pretty", False),
                                   metrics=getattr(s, "obs_stdout_metrics", False)),
    "sqlite": _sqlite_builder,
    "prometheus": lambda s: PrometheusSink(path=getattr(s, "obs_prometheus_path", "/metrics"),
                                           token=_sec(getattr(s, "obs_prometheus_token", ""))),
    "webhook": lambda s: WebhookSink(url=s.obs_webhook_url,
                                     token=_sec(getattr(s, "obs_webhook_token", "")),
                                     batch=getattr(s, "obs_webhook_batch", 100)),
    "otlp": lambda s: OtlpSink(endpoint=s.obs_otlp_endpoint,
                               headers=_sec(getattr(s, "obs_otlp_headers", "")),
                               service_name=getattr(s, "observability_service_name", "knowledgedesk")),
    # Centralized log/event collection, config-selected — see docs/LOGGING.md.
    "postgres": lambda s: PostgresSink(dsn=_sec(getattr(s, "obs_postgres_dsn", "")),
                                       table=getattr(s, "obs_postgres_table", "kd_logs"),
                                       batch=getattr(s, "obs_postgres_batch", 50)),
    "mongodb": lambda s: MongoSink(uri=_sec(getattr(s, "obs_mongo_uri", "")),
                                   database=getattr(s, "obs_mongo_db", "knowledgedesk"),
                                   collection=getattr(s, "obs_mongo_collection", "logs"),
                                   batch=getattr(s, "obs_mongo_batch", 50)),
}


def build_sinks(settings, names: list[str]) -> list[Sink]:
    built: list[Sink] = []
    for name in names:
        name = name.strip().lower()
        if not name:
            continue
        builder = SINK_BUILDERS.get(name)
        if not builder:
            log.warning("observability: unknown sink '%s' — skipped", name)
            continue
        try:
            built.append(builder(settings))
        except Exception:                # a broken sink must not break startup
            log.exception("observability: sink '%s' failed to initialise", name)
    return built
