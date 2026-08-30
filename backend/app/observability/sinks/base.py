"""Sink contract.

A sink receives already-built signals and does something with them — print,
store, forward. Implement only the methods you care about; the rest no-op.

Set ``blocking = True`` if a method does network / slow I/O: the dispatcher
will then feed this sink from a background thread through a bounded queue,
never on the request path.
"""
from __future__ import annotations

from ..models import Event, Sample, Span


class Sink:
    #: identifier used in OBSERVABILITY_SINKS
    name: str = "sink"
    #: True → dispatcher forwards to this sink off-thread, drop-on-overflow
    blocking: bool = False

    def on_metric(self, sample: Sample) -> None:  # noqa: D401
        pass

    def on_event(self, event: Event) -> None:
        pass

    def on_span(self, span: Span) -> None:
        pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass
