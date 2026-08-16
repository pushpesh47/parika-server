"""
PARIKA Router

Provides the core component responsible for routing validated
requests to the appropriate execution path.

Router maintains the authoritative runtime registry of Route
definitions, selects the appropriate Route for an incoming request
using each route's matcher predicate, and coordinates dispatch by
invoking the selected route's handler.

Router does not plan execution (owned by Planner) and does not
execute business logic itself. Matcher predicates and handlers are
treated as opaque callables owned by the component that registered
the route.
"""

from __future__ import annotations

from threading import RLock
from typing import Any

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

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
)
from .route import Route

ROUTE_REGISTERED_EVENT = "router.route.registered"
ROUTE_UNREGISTERED_EVENT = "router.route.unregistered"
DISPATCH_STARTED_EVENT = "router.dispatch.started"
DISPATCH_COMPLETED_EVENT = "router.dispatch.completed"
DISPATCH_FAILED_EVENT = "router.dispatch.failed"


class Router:
    """
    Routes validated requests to the appropriate execution path.

    Router owns the authoritative runtime registry of Route
    definitions. It selects the best matching Route for a request and
    coordinates dispatch to that Route's handler.

    Router intentionally does not:

    - Plan execution. That belongs to Planner.
    - Execute business logic. Handlers are opaque callables owned by
      the component that registered the route.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize the Router.

        Args:
            event_bus:
                EventBus used to publish routing and dispatch events.

            logger:
                PARIKA Logger component.
        """

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._lock = RLock()
        self._routes: dict[str, Route] = {}

    # ------------------------------------------------------------------
    # Route Registry
    # ------------------------------------------------------------------

    def register_route(self, route: Route) -> None:
        """
        Register a Route.

        Args:
            route:
                Route to register.

        Raises:
            RouteAlreadyRegisteredError:
                If a route with the same identifier is already
                registered.
        """

        with self._lock:
            if route.id in self._routes:
                raise RouteAlreadyRegisteredError(
                    f"Route '{route.id}' is already registered."
                )

            self._routes[route.id] = route

        self._event_bus.publish(
            ROUTE_REGISTERED_EVENT,
            RouteRegisteredEvent(route_id=route.id),
        )

        self._logger.debug(
            "Registered route '%s'.",
            route.id,
        )

    def unregister_route(self, route_id: str) -> None:
        """
        Unregister a Route.

        Raises:
            RouteNotFoundError:
                If the route is not registered.
        """

        with self._lock:
            self._require_route(route_id)

            del self._routes[route_id]

        self._event_bus.publish(
            ROUTE_UNREGISTERED_EVENT,
            RouteUnregisteredEvent(route_id=route_id),
        )

        self._logger.debug(
            "Unregistered route '%s'.",
            route_id,
        )

    def get(self, route_id: str) -> Route:
        """
        Retrieve a registered Route.

        Raises:
            RouteNotFoundError:
                If the route is not registered.
        """

        with self._lock:
            return self._require_route(route_id)

    def contains(self, route_id: str) -> bool:
        """
        Determine whether a Route is registered.
        """

        with self._lock:
            return route_id in self._routes

    def get_all(self) -> tuple[Route, ...]:
        """
        Return every registered Route.
        """

        with self._lock:
            return tuple(self._routes.values())

    def count(self) -> int:
        """
        Return the number of registered Routes.
        """

        with self._lock:
            return len(self._routes)

    # ------------------------------------------------------------------
    # Selection and Dispatch
    # ------------------------------------------------------------------

    def select(self, request: Any) -> Route:
        """
        Select the best matching Route for a request.

        Every registered route's matcher is evaluated against the
        request. A matcher that raises an exception is logged and
        treated as not matching.

        When multiple routes match, the route with the highest
        priority is selected. Ties are broken by registration order.

        Args:
            request:
                Opaque request to select a route for.

        Returns:
            The selected Route.

        Raises:
            NoMatchingRouteError:
                If no registered route matches the request.
        """

        with self._lock:
            routes_snapshot = tuple(self._routes.values())

        matched: list[Route] = []

        for route in routes_snapshot:

            try:
                matches = route.matcher(request)

            except Exception:
                self._logger.exception(
                    "Route '%s' matcher raised an exception; "
                    "treating as not matched.",
                    route.id,
                )
                continue

            if matches:
                matched.append(route)

        if not matched:
            raise NoMatchingRouteError(
                "No registered route matches the supplied request."
            )

        return max(matched, key=lambda route: route.priority)

    def dispatch(self, request: Any) -> Any:
        """
        Select a Route for a request and invoke its handler.

        Args:
            request:
                Opaque request to dispatch.

        Returns:
            The value returned by the selected route's handler.

        Raises:
            NoMatchingRouteError:
                If no registered route matches the request.

            DispatchError:
                If the selected route's handler raises an exception.
        """

        route = self.select(request)

        self._event_bus.publish(
            DISPATCH_STARTED_EVENT,
            DispatchStartedEvent(route_id=route.id),
        )

        if route.log_dispatch:
            self._logger.debug(
                "Dispatching request to route '%s'.",
                route.id,
            )

        try:
            result = route.handler(request)

        except Exception as ex:
            self._event_bus.publish(
                DISPATCH_FAILED_EVENT,
                DispatchFailedEvent(route_id=route.id, reason=str(ex)),
            )

            # Always logged, regardless of `route.log_dispatch` --
            # suppressing routine start/completion noise for
            # high-frequency polling routes must never suppress error
            # visibility.
            self._logger.exception(
                "Dispatch to route '%s' failed.",
                route.id,
            )

            raise DispatchError(
                f"Dispatch to route '{route.id}' failed."
            ) from ex

        self._event_bus.publish(
            DISPATCH_COMPLETED_EVENT,
            DispatchCompletedEvent(route_id=route.id),
        )

        if route.log_dispatch:
            self._logger.debug(
                "Dispatch to route '%s' completed.",
                route.id,
            )

        return result

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _require_route(self, route_id: str) -> Route:
        """
        Retrieve a registered Route.

        Raises:
            RouteNotFoundError:
                If the route is not registered.

        Notes:
            This helper assumes the caller already holds the registry
            lock.
        """

        try:
            return self._routes[route_id]

        except KeyError as ex:
            raise RouteNotFoundError(
                f"Route '{route_id}' is not registered."
            ) from ex
