"""
Unit tests for `MediaToolDriver` - the `ToolDriver` implementing every
`media.*` Capability.

`MediaToolDriver` never claims playback succeeded: every command
handler reports either `"status": "dispatched"` (enqueued to a
connected Web Client) or `"status": "unavailable"` (no Web Client
connected) - never `"status": "success"` implying actual playback.
`test_non_blocking.py`-style proof of non-blocking dispatch lives in
`TestNonBlockingPlay` below, reusing the busy-loop pattern from
`test_connection_registry.py`.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Mapping

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.tools.media.connection_registry import MediaConnectionRegistry
from parika.tools.media.driver import MediaToolDriver
from parika.tools.media.manifest import MediaOperation
from parika.tools.media.model import PlaybackStatus
from parika.tools.media.resolution import MediaResolver
from parika.tools.media.security import LocalMediaPathSecurity, LocalMediaPathSecurityConfig
from parika.tools.media.state_store import MediaStateStore


class FakeDispatcher:
    """
    Fake `MediaCommandDispatcher` - records every dispatched message,
    and simulates "no Web Client connected" when `connected=False`.
    """

    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected
        self.messages: list[Mapping[str, Any]] = []

    def dispatch(self, message: Mapping[str, Any]) -> bool:
        if not self.connected:
            return False

        self.messages.append(message)
        return True

    def is_connected(self) -> bool:
        return self.connected


@pytest.fixture
def state_store() -> MediaStateStore:
    return MediaStateStore()


@pytest.fixture
def resolver(tmp_path: Path) -> MediaResolver:
    return MediaResolver(
        path_security=LocalMediaPathSecurity(LocalMediaPathSecurityConfig()),
        brain=None,
    )


def _driver(
    operation: MediaOperation,
    *,
    dispatcher: FakeDispatcher,
    state_store: MediaStateStore,
    resolver: MediaResolver,
) -> MediaToolDriver:
    return MediaToolDriver(
        operation, state_store=state_store, dispatcher=dispatcher, resolver=resolver
    )


class TestPlay:
    def test_play_resolves_and_dispatches_a_youtube_url(
        self, state_store: MediaStateStore, resolver: MediaResolver
    ) -> None:
        dispatcher = FakeDispatcher()
        driver = _driver(
            MediaOperation.PLAY, dispatcher=dispatcher, state_store=state_store, resolver=resolver
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "https://youtu.be/dQw4w9WgXcQ"})
        )

        assert response.result["status"] == "dispatched"
        assert response.result["source"]["type"] == "youtube"
        assert dispatcher.messages == [
            {
                "type": "media.play",
                "payload": {"source": response.result["source"]},
            }
        ]
        assert state_store.get().status is PlaybackStatus.LOADING

    def test_play_reports_unavailable_without_a_connected_client(
        self, state_store: MediaStateStore, resolver: MediaResolver
    ) -> None:
        dispatcher = FakeDispatcher(connected=False)
        driver = _driver(
            MediaOperation.PLAY, dispatcher=dispatcher, state_store=state_store, resolver=resolver
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "https://youtu.be/dQw4w9WgXcQ"})
        )

        assert response.result["status"] == "unavailable"
        assert dispatcher.messages == []
        # Never falsely advances state when nothing was dispatched.
        assert state_store.get().status is PlaybackStatus.IDLE

    def test_play_reports_unsupported_for_a_webpage_url(
        self, state_store: MediaStateStore, resolver: MediaResolver
    ) -> None:
        dispatcher = FakeDispatcher()
        driver = _driver(
            MediaOperation.PLAY, dispatcher=dispatcher, state_store=state_store, resolver=resolver
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "https://example.com/page"})
        )

        assert response.result["status"] == "unsupported"
        assert dispatcher.messages == []

    def test_play_reports_not_found_for_free_text_with_no_search_resolver(
        self, state_store: MediaStateStore, resolver: MediaResolver
    ) -> None:
        dispatcher = FakeDispatcher()
        driver = _driver(
            MediaOperation.PLAY, dispatcher=dispatcher, state_store=state_store, resolver=resolver
        )

        response = driver.execute(
            ToolRequest(arguments={"query": "Imagine Dragons Believer"})
        )

        assert response.result["status"] == "not_found"

    def test_play_requires_a_non_empty_query(
        self, state_store: MediaStateStore, resolver: MediaResolver
    ) -> None:
        from parika.tools.media.exceptions import MediaValidationError

        dispatcher = FakeDispatcher()
        driver = _driver(
            MediaOperation.PLAY, dispatcher=dispatcher, state_store=state_store, resolver=resolver
        )

        with pytest.raises(MediaValidationError):
            driver.execute(ToolRequest(arguments={"query": "   "}))


@pytest.mark.parametrize(
    "operation,command_type",
    [
        (MediaOperation.PAUSE, "media.pause"),
        (MediaOperation.RESUME, "media.resume"),
        (MediaOperation.STOP, "media.stop"),
        (MediaOperation.SKIP, "media.skip"),
        (MediaOperation.PREVIOUS, "media.previous"),
        (MediaOperation.MUTE, "media.mute"),
        (MediaOperation.UNMUTE, "media.unmute"),
        (MediaOperation.SHOW, "media.show"),
        (MediaOperation.HIDE, "media.hide"),
    ],
)
class TestSimpleCommands:
    def test_dispatches_when_a_client_is_connected(
        self,
        operation: MediaOperation,
        command_type: str,
        state_store: MediaStateStore,
        resolver: MediaResolver,
    ) -> None:
        dispatcher = FakeDispatcher()
        driver = _driver(
            operation, dispatcher=dispatcher, state_store=state_store, resolver=resolver
        )

        response = driver.execute(ToolRequest(arguments={}))

        assert response.result == {"status": "dispatched", "command": command_type}
        assert dispatcher.messages == [{"type": command_type}]

    def test_reports_unavailable_without_a_connected_client(
        self,
        operation: MediaOperation,
        command_type: str,
        state_store: MediaStateStore,
        resolver: MediaResolver,
    ) -> None:
        dispatcher = FakeDispatcher(connected=False)
        driver = _driver(
            operation, dispatcher=dispatcher, state_store=state_store, resolver=resolver
        )

        response = driver.execute(ToolRequest(arguments={}))

        assert response.result["status"] == "unavailable"
        assert dispatcher.messages == []


class TestSeek:
    def test_dispatches_a_valid_position(
        self, state_store: MediaStateStore, resolver: MediaResolver
    ) -> None:
        dispatcher = FakeDispatcher()
        driver = _driver(
            MediaOperation.SEEK, dispatcher=dispatcher, state_store=state_store, resolver=resolver
        )

        response = driver.execute(ToolRequest(arguments={"position_seconds": 90}))

        assert response.result["status"] == "dispatched"
        assert dispatcher.messages == [
            {"type": "media.seek", "payload": {"position_seconds": 90.0}}
        ]

    @pytest.mark.parametrize("bad_position", [-1, "not-a-number", None])
    def test_rejects_an_invalid_position(
        self, bad_position: Any, state_store: MediaStateStore, resolver: MediaResolver
    ) -> None:
        dispatcher = FakeDispatcher()
        driver = _driver(
            MediaOperation.SEEK, dispatcher=dispatcher, state_store=state_store, resolver=resolver
        )

        response = driver.execute(
            ToolRequest(arguments={"position_seconds": bad_position})
        )

        assert response.result["status"] == "invalid"
        assert dispatcher.messages == []


class TestSetVolume:
    def test_dispatches_a_valid_volume(
        self, state_store: MediaStateStore, resolver: MediaResolver
    ) -> None:
        dispatcher = FakeDispatcher()
        driver = _driver(
            MediaOperation.SET_VOLUME,
            dispatcher=dispatcher,
            state_store=state_store,
            resolver=resolver,
        )

        response = driver.execute(ToolRequest(arguments={"volume_percent": 50}))

        assert response.result["status"] == "dispatched"
        assert dispatcher.messages == [
            {"type": "media.set_volume", "payload": {"volume_percent": 50.0}}
        ]

    @pytest.mark.parametrize("bad_volume", [-1, 101, "loud"])
    def test_rejects_an_invalid_volume(
        self, bad_volume: Any, state_store: MediaStateStore, resolver: MediaResolver
    ) -> None:
        dispatcher = FakeDispatcher()
        driver = _driver(
            MediaOperation.SET_VOLUME,
            dispatcher=dispatcher,
            state_store=state_store,
            resolver=resolver,
        )

        response = driver.execute(ToolRequest(arguments={"volume_percent": bad_volume}))

        assert response.result["status"] == "invalid"
        assert dispatcher.messages == []


class TestGetState:
    def test_reads_state_without_dispatching_anything(
        self, state_store: MediaStateStore, resolver: MediaResolver
    ) -> None:
        dispatcher = FakeDispatcher()
        driver = _driver(
            MediaOperation.GET_STATE,
            dispatcher=dispatcher,
            state_store=state_store,
            resolver=resolver,
        )

        response = driver.execute(ToolRequest(arguments={}))

        assert response.result["status"] == "success"
        assert response.result["state"]["status"] == "idle"
        assert dispatcher.messages == []

    def test_reflects_state_store_updates(
        self, state_store: MediaStateStore, resolver: MediaResolver
    ) -> None:
        state_store.apply_client_event("media.play_started", {})

        dispatcher = FakeDispatcher()
        driver = _driver(
            MediaOperation.GET_STATE,
            dispatcher=dispatcher,
            state_store=state_store,
            resolver=resolver,
        )

        response = driver.execute(ToolRequest(arguments={}))

        assert response.result["state"]["status"] == "playing"


class _EchoToolDriver:
    """Trivial, unrelated ToolDriver used only to prove independent work can proceed."""

    def execute(self, request: ToolRequest) -> ToolResponse:
        return ToolResponse(result={"echo": request.arguments.get("value")})


class TestNonBlockingPlay:
    def test_media_play_returns_promptly_even_while_the_web_client_is_busy(
        self, resolver: MediaResolver
    ) -> None:
        """
        Reuses `test_connection_registry.py`'s busy-loop pattern one
        level up, through the real `MediaToolDriver`/`ToolManager`
        pipeline: dispatching `media.play` to a Web Client whose
        event-loop thread is currently monopolized must still return
        almost immediately, and an entirely unrelated Tool call must
        be able to execute right after it, unaffected - proving media
        dispatch never blocks the rest of PARIKA's synchronous request
        processing (see the Media task's "Non-Blocking Requirement").
        """

        from parika.core.configuration.configuration import Configuration
        from parika.core.event_bus.event_bus import EventBus
        from parika.core.logger.logger import Logger
        from parika.core.tool_manager.tool import Tool
        from parika.core.tool_manager.tool_manager import ToolManager

        logger = Logger(Configuration())
        event_bus = EventBus(logger=logger)
        tool_manager = ToolManager(event_bus=event_bus, logger=logger)

        started = threading.Event()
        release = threading.Event()
        loop = asyncio.new_event_loop()

        async def _busy() -> None:
            started.set()
            deadline = time.perf_counter() + 2.0
            while not release.is_set() and time.perf_counter() < deadline:
                pass

        def _run_loop() -> None:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_busy())

        thread = threading.Thread(target=_run_loop, daemon=True)
        thread.start()

        try:
            assert started.wait(timeout=2.0), "busy Web Client loop never started"

            connection_registry = MediaConnectionRegistry()
            connection_registry.register(
                "busy-client", loop=loop, outbound=asyncio.Queue()
            )
            connection_registry.mark_ready("busy-client")

            media_driver = MediaToolDriver(
                MediaOperation.PLAY,
                state_store=MediaStateStore(),
                dispatcher=connection_registry,
                resolver=resolver,
            )
            tool_manager.register(
                Tool(
                    id="tool.media_play",
                    name="Media Play",
                    version="1.0.0",
                    description="test",
                    capabilities=("media.play",),
                ),
                media_driver,
            )
            tool_manager.register(
                Tool(
                    id="tool.echo",
                    name="Echo",
                    version="1.0.0",
                    description="test",
                    capabilities=("test.echo",),
                ),
                _EchoToolDriver(),
            )

            start_time = time.perf_counter()
            play_response = tool_manager.execute(
                "tool.media_play",
                ToolRequest(arguments={"query": "https://youtu.be/dQw4w9WgXcQ"}),
            )
            elapsed_seconds = time.perf_counter() - start_time

            assert play_response.result["status"] == "dispatched"
            assert elapsed_seconds < 0.5, (
                "media.play dispatch must not block on a busy Web "
                f"Client; took {elapsed_seconds:.3f}s"
            )

            # Unrelated PARIKA work proceeds immediately, while the
            # Web Client is still (from PARIKA's perspective) busy
            # loading/playing.
            echo_response = tool_manager.execute(
                "tool.echo", ToolRequest(arguments={"value": "weather?"})
            )
            assert echo_response.result == {"echo": "weather?"}

        finally:
            release.set()
            thread.join(timeout=3.0)
