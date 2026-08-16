"""
Unit tests for `MediaStateStore` - PARIKA's shared, last-known
`MediaState` holder.
"""

from __future__ import annotations

from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.tools.media.events import MEDIA_STATE_CHANGED_EVENT, MediaStateChangedEvent
from parika.tools.media.model import MediaSource, MediaSourceType, PlaybackStatus
from parika.tools.media.state_store import MediaStateStore


def _event_bus() -> EventBus:
    return EventBus(logger=Logger(Configuration()))


class TestMediaStateStoreCommandEffects:
    def test_record_command_dispatched_play_moves_to_loading(self) -> None:
        store = MediaStateStore()
        source = MediaSource(
            source_type=MediaSourceType.YOUTUBE, url="https://youtu.be/x", media_id="x"
        )

        state = store.record_command_dispatched("media.play", source=source)

        assert state.status is PlaybackStatus.LOADING
        assert state.source is source

    def test_record_command_dispatched_pause_never_changes_status(self) -> None:
        store = MediaStateStore()
        before = store.get()

        state = store.record_command_dispatched("media.pause", source=None)

        assert state.status == before.status


class TestMediaStateStoreClientEvents:
    def test_play_started_moves_to_playing(self) -> None:
        store = MediaStateStore()

        state = store.apply_client_event("media.play_started", {})

        assert state.status is PlaybackStatus.PLAYING

    def test_play_paused_moves_to_paused(self) -> None:
        store = MediaStateStore()

        state = store.apply_client_event("media.play_paused", {})

        assert state.status is PlaybackStatus.PAUSED

    def test_position_changed_updates_only_position(self) -> None:
        store = MediaStateStore()
        store.apply_client_event("media.play_started", {})

        state = store.apply_client_event("media.position_changed", {"position": 42.0})

        assert state.status is PlaybackStatus.PLAYING
        assert state.position == 42.0

    def test_error_event_sets_status_and_message(self) -> None:
        store = MediaStateStore()

        state = store.apply_client_event("media.error", {"message": "codec unsupported"})

        assert state.status is PlaybackStatus.ERROR
        assert state.error_message == "codec unsupported"

    def test_state_changed_merges_full_state_payload(self) -> None:
        store = MediaStateStore()

        state = store.apply_client_event(
            "media.state_changed",
            {
                "state": {
                    "status": "playing",
                    "position": 10.0,
                    "volume": 0.5,
                    "muted": True,
                    "source": {
                        "type": "direct_url",
                        "url": "https://example.com/a.mp3",
                    },
                }
            },
        )

        assert state.status is PlaybackStatus.PLAYING
        assert state.position == 10.0
        assert state.volume == 0.5
        assert state.muted is True
        assert state.source is not None
        assert state.source.source_type is MediaSourceType.DIRECT_URL

    def test_unrecognized_event_type_is_a_no_op(self) -> None:
        store = MediaStateStore()
        before = store.get()

        state = store.apply_client_event("media.some_future_event", {"anything": 1})

        assert state.status == before.status
        assert state.source == before.source

    def test_set_client_connected_only_changes_that_field(self) -> None:
        store = MediaStateStore()

        state = store.set_client_connected(True)
        assert state.client_connected is True

        state = store.set_client_connected(False)
        assert state.client_connected is False


class TestMediaStateStoreEventPublishing:
    def test_publishes_state_changed_event(self) -> None:
        event_bus = _event_bus()
        received: list[MediaStateChangedEvent] = []
        event_bus.subscribe(MEDIA_STATE_CHANGED_EVENT, received.append)

        store = MediaStateStore(event_bus=event_bus)
        store.apply_client_event("media.play_started", {})

        assert len(received) == 1
        assert received[0].state.status is PlaybackStatus.PLAYING
