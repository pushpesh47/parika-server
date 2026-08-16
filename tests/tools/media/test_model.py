"""
Unit tests for the Media domain model (`MediaSource`/`MediaState`).
"""

from __future__ import annotations

import pytest

from parika.tools.media.model import MediaSource, MediaSourceType, MediaState, PlaybackStatus


class TestMediaSource:
    def test_local_requires_path(self) -> None:
        with pytest.raises(ValueError):
            MediaSource(source_type=MediaSourceType.LOCAL)

        source = MediaSource(source_type=MediaSourceType.LOCAL, path="/music/a.mp3")
        assert source.path == "/music/a.mp3"

    def test_youtube_requires_url_and_media_id(self) -> None:
        with pytest.raises(ValueError):
            MediaSource(source_type=MediaSourceType.YOUTUBE, url="https://youtu.be/x")

        with pytest.raises(ValueError):
            MediaSource(source_type=MediaSourceType.YOUTUBE, media_id="x")

        source = MediaSource(
            source_type=MediaSourceType.YOUTUBE,
            url="https://youtu.be/x",
            media_id="x",
        )
        assert source.media_id == "x"

    @pytest.mark.parametrize("source_type", [MediaSourceType.DIRECT_URL, MediaSourceType.STREAM])
    def test_direct_url_and_stream_require_url(self, source_type: MediaSourceType) -> None:
        with pytest.raises(ValueError):
            MediaSource(source_type=source_type)

        source = MediaSource(source_type=source_type, url="https://example.com/a.mp3")
        assert source.url == "https://example.com/a.mp3"

    def test_to_dict_is_json_serializable_shape(self) -> None:
        source = MediaSource(
            source_type=MediaSourceType.YOUTUBE,
            url="https://youtu.be/x",
            media_id="x",
            title="A Song",
            artist="An Artist",
        )

        payload = source.to_dict()

        assert payload == {
            "type": "youtube",
            "url": "https://youtu.be/x",
            "path": None,
            "media_id": "x",
            "title": "A Song",
            "artist": "An Artist",
            "album": None,
            "duration": None,
            "mime_type": None,
        }


class TestMediaState:
    def test_initial_state_is_idle_and_disconnected(self) -> None:
        state = MediaState.initial()

        assert state.status is PlaybackStatus.IDLE
        assert state.source is None
        assert state.client_connected is False

    def test_to_dict_serializes_source_and_status(self) -> None:
        source = MediaSource(source_type=MediaSourceType.LOCAL, path="/music/a.mp3")
        state = MediaState(status=PlaybackStatus.PLAYING, source=source, position=1.5)

        payload = state.to_dict()

        assert payload["status"] == "playing"
        assert payload["source"]["type"] == "local"
        assert payload["position"] == 1.5
