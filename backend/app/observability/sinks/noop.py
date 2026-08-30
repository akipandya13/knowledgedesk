"""Does nothing. The safe default and a template for new sinks."""
from __future__ import annotations

from .base import Sink


class NoopSink(Sink):
    name = "noop"
