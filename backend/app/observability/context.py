"""Ambient request/trace context.

The HTTP middleware binds `request_id`, `tenant`, `actor` and `route` for the
duration of a request; spans and events created anywhere below that pick the
values up automatically so a sink can correlate them without every call site
threading identifiers through.

contextvars are task-local (asyncio) and thread-local — safe under Starlette's
threadpool for sync routes.
"""
from __future__ import annotations

import contextvars
import secrets
from dataclasses import dataclass

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("obs_request_id", default=None)
_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar("obs_tenant", default=None)
_actor: contextvars.ContextVar[str | None] = contextvars.ContextVar("obs_actor", default=None)
_route: contextvars.ContextVar[str | None] = contextvars.ContextVar("obs_route", default=None)
# Stack of active span ids, innermost last — used for parent linkage.
_span_stack: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("obs_span_stack", default=())


@dataclass
class Snapshot:
    request_id: str | None
    tenant: str | None
    actor: str | None
    route: str | None
    span_id: str | None


def new_id(n: int = 8) -> str:
    return secrets.token_hex(n)


def bind(*, request_id: str | None = None, tenant: str | None = None,
         actor: str | None = None, route: str | None = None) -> list:
    """Set any provided fields; return reset tokens for `unbind`."""
    tokens = []
    if request_id is not None:
        tokens.append((_request_id, _request_id.set(request_id)))
    if tenant is not None:
        tokens.append((_tenant, _tenant.set(tenant)))
    if actor is not None:
        tokens.append((_actor, _actor.set(actor)))
    if route is not None:
        tokens.append((_route, _route.set(route)))
    return tokens


def unbind(tokens: list) -> None:
    for var, tok in reversed(tokens):
        try:
            var.reset(tok)
        except (ValueError, LookupError):
            pass


def current() -> Snapshot:
    stack = _span_stack.get()
    return Snapshot(
        request_id=_request_id.get(),
        tenant=_tenant.get(),
        actor=_actor.get(),
        route=_route.get(),
        span_id=stack[-1] if stack else None,
    )


def push_span(span_id: str):
    return _span_stack.set(_span_stack.get() + (span_id,))


def pop_span(token) -> None:
    try:
        _span_stack.reset(token)
    except (ValueError, LookupError):
        pass


def request_id() -> str | None:
    return _request_id.get()


def tenant() -> str | None:
    return _tenant.get()


def reset_all() -> None:
    """Clear every ambient field. The HTTP middleware calls this after each
    request so nothing leaks into a reused context/thread."""
    for var in (_request_id, _tenant, _actor, _route):
        var.set(None)
    _span_stack.set(())
