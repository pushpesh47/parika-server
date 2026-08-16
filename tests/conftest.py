"""
Shared pytest fixtures and test helpers for the PARIKA test suite.

These fixtures provide the small set of dependencies almost every Core
component test needs: a real `Logger` (required verbatim by
`ToolManager` and `ProviderManager`, which strictly type-check it) and
a real `EventBus` built on top of it.

Individual test modules may still define their own local fixtures when
they need a differently configured instance; these shared fixtures
only remove the boilerplate that was otherwise repeated across every
test file.
"""

from __future__ import annotations

from typing import Any

import pytest

from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


class RecordingSubscriber:
    """
    EventBus subscriber that records every payload it receives.

    Shared across test modules to assert on published events without
    each module reimplementing the same tiny helper.
    """

    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


class ProgressLifecycleRecorder:
    """
    Subscribes to the generic `progress.*` channels and records every
    `progress.started` event alongside every matching
    `progress.completed`/`progress.failed` event, keyed by
    `ProgressEvent.progress_id`.

    Used to assert PARIKA's ProgressReporter lifecycle contract --
    "every `started()` has exactly one matching `completed()`/
    `failed()`" -- directly against the events a component actually
    published, independent of any CLI/spinner rendering.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self.started_events: dict[str, list[Any]] = {}
        self.terminal_events: dict[str, list[Any]] = {}

        event_bus.subscribe("progress.started", self._on_started)
        event_bus.subscribe("progress.completed", self._on_terminal)
        event_bus.subscribe("progress.failed", self._on_terminal)

    def _on_started(self, event: Any) -> None:
        self.started_events.setdefault(event.progress_id, []).append(event)

    def _on_terminal(self, event: Any) -> None:
        self.terminal_events.setdefault(event.progress_id, []).append(event)

    def assert_every_started_has_exactly_one_terminal(self) -> None:
        """
        Assert that every observed `progress_id` that reached
        `started()` received exactly one terminal event, and that no
        terminal event was observed for a `progress_id` that never
        started.
        """

        for progress_id, starts in self.started_events.items():
            terminals = self.terminal_events.get(progress_id, [])
            assert len(terminals) == 1, (
                f"progress_id {progress_id!r} (source_id "
                f"{starts[0].source_id!r}) started {len(starts)} "
                f"time(s) but received {len(terminals)} terminal "
                f"event(s); expected exactly 1."
            )

        for progress_id in self.terminal_events:
            assert progress_id in self.started_events, (
                f"progress_id {progress_id!r} received a terminal "
                "event without ever starting."
            )


@pytest.fixture
def configuration() -> Configuration:
    """
    Unloaded Configuration instance.

    `Configuration.get()` returns defaults for any key when `load()`
    has not been called, which is sufficient for unit tests that do
    not depend on specific configured values.
    """

    return Configuration()


@pytest.fixture
def logger(configuration: Configuration) -> Logger:
    """
    Real Logger instance.

    `ToolManager` and `ProviderManager` both perform a strict
    `type(logger) is Logger` check in their constructors, so tests
    exercising them (directly or transitively) must use a real Logger
    rather than a fake.
    """

    return Logger(configuration)


@pytest.fixture
def event_bus(logger: Logger) -> EventBus:
    """
    Real EventBus instance built on the shared `logger` fixture.
    """

    return EventBus(logger)
