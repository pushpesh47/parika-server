"""
Unit tests for Router.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.router.events import (
    DispatchCompletedEvent,
    DispatchFailedEvent,
    DispatchStartedEvent,
    RouteRegisteredEvent,
    RouteUnregisteredEvent,
)
from parika.core.router.exceptions import (
    DispatchError,
    NoMatchingRouteError,
    RouteAlreadyRegisteredError,
    RouteNotFoundError,
)
from parika.core.router.route import Route
from parika.core.router.router import Router


class _FakeLogger:
    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


class RecordingSubscriber:
    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(logger=_FakeLogger())  # type: ignore[arg-type]


@pytest.fixture
def router(event_bus: EventBus) -> Router:
    return Router(event_bus=event_bus, logger=_FakeLogger())  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# register_route() / unregister_route() / registry
# ---------------------------------------------------------------------


class TestRegistry:
    def test_registers_route(
        self,
        router: Router,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("router.route.registered", subscriber)

        route = Route(
            id="task",
            matcher=lambda req: True,
            handler=lambda req: "handled",
        )
        router.register_route(route)

        assert router.contains("task")
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], RouteRegisteredEvent)

    def test_rejects_duplicate_route_id(
        self,
        router: Router,
    ) -> None:
        route = Route(
            id="task", matcher=lambda req: True, handler=lambda req: None
        )
        router.register_route(route)

        with pytest.raises(RouteAlreadyRegisteredError):
            router.register_route(route)

    def test_unregister_removes_route(
        self,
        router: Router,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("router.route.unregistered", subscriber)

        route = Route(
            id="task", matcher=lambda req: True, handler=lambda req: None
        )
        router.register_route(route)
        router.unregister_route("task")

        assert not router.contains("task")
        assert len(subscriber.received) == 1
        assert isinstance(subscriber.received[0], RouteUnregisteredEvent)

    def test_unregister_raises_when_missing(
        self,
        router: Router,
    ) -> None:
        with pytest.raises(RouteNotFoundError):
            router.unregister_route("missing")

    def test_get_raises_when_missing(
        self,
        router: Router,
    ) -> None:
        with pytest.raises(RouteNotFoundError):
            router.get("missing")

    def test_get_all_and_count(
        self,
        router: Router,
    ) -> None:
        router.register_route(
            Route(id="a", matcher=lambda req: True, handler=lambda req: None)
        )
        router.register_route(
            Route(id="b", matcher=lambda req: True, handler=lambda req: None)
        )

        assert router.count() == 2
        assert {route.id for route in router.get_all()} == {"a", "b"}


# ---------------------------------------------------------------------
# select()
# ---------------------------------------------------------------------


class TestSelect:
    def test_selects_matching_route(
        self,
        router: Router,
    ) -> None:
        router.register_route(
            Route(
                id="task",
                matcher=lambda req: req.get("kind") == "task",
                handler=lambda req: None,
            )
        )
        router.register_route(
            Route(
                id="workflow",
                matcher=lambda req: req.get("kind") == "workflow",
                handler=lambda req: None,
            )
        )

        selected = router.select({"kind": "workflow"})

        assert selected.id == "workflow"

    def test_raises_when_no_route_matches(
        self,
        router: Router,
    ) -> None:
        router.register_route(
            Route(
                id="task",
                matcher=lambda req: False,
                handler=lambda req: None,
            )
        )

        with pytest.raises(NoMatchingRouteError):
            router.select({"kind": "unknown"})

    def test_higher_priority_route_wins(
        self,
        router: Router,
    ) -> None:
        router.register_route(
            Route(
                id="low",
                matcher=lambda req: True,
                handler=lambda req: None,
                priority=1,
            )
        )
        router.register_route(
            Route(
                id="high",
                matcher=lambda req: True,
                handler=lambda req: None,
                priority=10,
            )
        )

        selected = router.select({})

        assert selected.id == "high"

    def test_broken_matcher_is_treated_as_not_matched(
        self,
        router: Router,
    ) -> None:
        def _boom(request: Any) -> bool:
            raise RuntimeError("boom")

        router.register_route(
            Route(id="broken", matcher=_boom, handler=lambda req: None)
        )
        router.register_route(
            Route(
                id="working",
                matcher=lambda req: True,
                handler=lambda req: None,
            )
        )

        selected = router.select({})

        assert selected.id == "working"


# ---------------------------------------------------------------------
# dispatch()
# ---------------------------------------------------------------------


class TestDispatch:
    def test_dispatch_invokes_handler_and_returns_result(
        self,
        router: Router,
    ) -> None:
        router.register_route(
            Route(
                id="task",
                matcher=lambda req: True,
                handler=lambda req: f"handled:{req}",
            )
        )

        result = router.dispatch("payload")

        assert result == "handled:payload"

    def test_dispatch_publishes_started_and_completed_events(
        self,
        router: Router,
        event_bus: EventBus,
    ) -> None:
        started = RecordingSubscriber()
        completed = RecordingSubscriber()
        event_bus.subscribe("router.dispatch.started", started)
        event_bus.subscribe("router.dispatch.completed", completed)

        router.register_route(
            Route(id="task", matcher=lambda req: True, handler=lambda req: None)
        )

        router.dispatch({})

        assert len(started.received) == 1
        assert isinstance(started.received[0], DispatchStartedEvent)
        assert len(completed.received) == 1
        assert isinstance(completed.received[0], DispatchCompletedEvent)

    def test_dispatch_raises_when_no_route_matches(
        self,
        router: Router,
    ) -> None:
        with pytest.raises(NoMatchingRouteError):
            router.dispatch({})

    def test_dispatch_wraps_handler_exception(
        self,
        router: Router,
        event_bus: EventBus,
    ) -> None:
        failed = RecordingSubscriber()
        event_bus.subscribe("router.dispatch.failed", failed)

        def _boom(request: Any) -> Any:
            raise RuntimeError("boom")

        router.register_route(
            Route(id="task", matcher=lambda req: True, handler=_boom)
        )

        with pytest.raises(DispatchError) as excinfo:
            router.dispatch({})

        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert len(failed.received) == 1
        assert isinstance(failed.received[0], DispatchFailedEvent)


# ---------------------------------------------------------------------
# dispatch() logging / `Route.log_dispatch`
# ---------------------------------------------------------------------


class TestDispatchLogging:
    """
    Covers the request-dispatch-noise-suppression mechanism:
    `Route.log_dispatch` (default `True`) controls only the two
    routine debug entries `Router.dispatch()` would otherwise always
    emit -- it never affects `EventBus` events, and it never affects
    failure logging (see `Router.dispatch()`'s own comment).
    """

    def test_normal_route_still_logs_dispatch_start_and_completion(
        self,
        router: Router,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        router.register_route(
            Route(id="task", matcher=lambda req: True, handler=lambda req: "ok")
        )

        with caplog.at_level("DEBUG", logger="parika.core.router.router"):
            router.dispatch({})

        assert "Dispatching request to route 'task'." in caplog.text
        assert "Dispatch to route 'task' completed." in caplog.text

    def test_quiet_route_suppresses_dispatch_start_and_completion_logs(
        self,
        router: Router,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        router.register_route(
            Route(
                id="status.get",
                matcher=lambda req: True,
                handler=lambda req: "ok",
                log_dispatch=False,
            )
        )

        with caplog.at_level("DEBUG", logger="parika.core.router.router"):
            router.dispatch({})

        assert "Dispatching request to route 'status.get'." not in caplog.text
        assert "Dispatch to route 'status.get' completed." not in caplog.text

    def test_quiet_route_dispatch_still_publishes_events(
        self,
        router: Router,
        event_bus: EventBus,
    ) -> None:
        """
        Suppressing routine logging must never suppress the
        `router.dispatch.*` `EventBus` events -- only the log-file
        entries change.
        """

        started = RecordingSubscriber()
        completed = RecordingSubscriber()
        event_bus.subscribe("router.dispatch.started", started)
        event_bus.subscribe("router.dispatch.completed", completed)

        router.register_route(
            Route(
                id="status.get",
                matcher=lambda req: True,
                handler=lambda req: "ok",
                log_dispatch=False,
            )
        )

        router.dispatch({})

        assert len(started.received) == 1
        assert len(completed.received) == 1

    def test_quiet_route_still_logs_when_the_handler_raises(
        self,
        router: Router,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Error visibility must never be suppressed, even for a route
        with `log_dispatch=False`.
        """

        def _boom(request: Any) -> Any:
            raise RuntimeError("boom")

        router.register_route(
            Route(
                id="status.get",
                matcher=lambda req: True,
                handler=_boom,
                log_dispatch=False,
            )
        )

        with caplog.at_level("DEBUG", logger="parika.core.router.router"):
            with pytest.raises(DispatchError):
                router.dispatch({})

        assert "Dispatch to route 'status.get' failed." in caplog.text

    def test_quiet_route_failure_still_publishes_the_failed_event(
        self,
        router: Router,
        event_bus: EventBus,
    ) -> None:
        failed = RecordingSubscriber()
        event_bus.subscribe("router.dispatch.failed", failed)

        def _boom(request: Any) -> Any:
            raise RuntimeError("boom")

        router.register_route(
            Route(
                id="status.get",
                matcher=lambda req: True,
                handler=_boom,
                log_dispatch=False,
            )
        )

        with pytest.raises(DispatchError):
            router.dispatch({})

        assert len(failed.received) == 1
        assert isinstance(failed.received[0], DispatchFailedEvent)

    def test_log_dispatch_defaults_to_true(self) -> None:
        route = Route(id="task", matcher=lambda req: True, handler=lambda req: None)

        assert route.log_dispatch is True
