"""
PARIKA Route

Defines the immutable Route registered with Router.

A Route pairs a matching predicate with the handler invoked when that
predicate matches an incoming request. Both the predicate and the
handler are treated as opaque callables owned by the component that
registers the route; Router never interprets their internals.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class Route:
    """
    Immutable execution path registered with Router.

    A Route determines, through an opaque matcher predicate, whether
    it applies to a given request, and delegates execution to an
    opaque handler when selected.
    """

    id: str
    """
    Unique identifier of the route.
    """

    matcher: Callable[[Any], bool]
    """
    Predicate that determines whether this route applies to a given
    request.
    """

    handler: Callable[[Any], Any]
    """
    Handler invoked with the request when this route is selected.

    The handler owns all business logic. Router only dispatches to
    it.
    """

    priority: int = 0
    """
    Relative priority used to select between multiple matching
    routes. Higher values take precedence.
    """

    description: str | None = None
    """
    Optional human-readable explanation of the route's purpose.
    """

    log_dispatch: bool = True
    """
    Whether `Router.dispatch()` emits its normal
    "Dispatching request to route '...'"/"Dispatch to route '...'
    completed." debug log entries for this route. Defaults to `True`
    (today's unchanged behavior) for every route.

    Set to `False` only for high-frequency, low-value routes (e.g.
    status/health polling) that would otherwise flood the log file
    with repetitive entries carrying no diagnostic value -- the
    component registering the route (never `Router` itself) decides
    this, keeping `Router` generic. This never affects
    `router.dispatch.*` `EventBus` events (still always published) or
    failure logging: a route with `log_dispatch=False` that raises is
    still logged via `Router.dispatch()`'s existing
    `self._logger.exception(...)` call, unconditionally.
    """
