"""
PARIKA Router package.

Provides the Router component and its primary public interfaces.
"""

from .events import (
    DispatchCompletedEvent,
    DispatchFailedEvent,
    DispatchStartedEvent,
    RouteRegisteredEvent,
    RouteUnregisteredEvent,
)
from .exceptions import (
    DispatchError,
    NoMatchingRouteError,
    RouteAlreadyRegisteredError,
    RouteNotFoundError,
    RouterError,
)
from .route import Route
from .router import Router

__all__ = [
    "DispatchCompletedEvent",
    "DispatchError",
    "DispatchFailedEvent",
    "DispatchStartedEvent",
    "NoMatchingRouteError",
    "Route",
    "RouteAlreadyRegisteredError",
    "RouteNotFoundError",
    "RouteRegisteredEvent",
    "RouteUnregisteredEvent",
    "Router",
    "RouterError",
]
