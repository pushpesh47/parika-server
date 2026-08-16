"""
Unit tests for `MediaResolver` - local path, direct URL, YouTube URL,
and free-text (`web.search`-backed) resolution.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.tools.media.exceptions import (
    MediaSourceNotFoundError,
    MediaUnsupportedSourceError,
    MediaValidationError,
)
from parika.tools.media.model import MediaSourceType
from parika.tools.media.resolution import MediaResolver
from parika.tools.media.security import LocalMediaPathSecurity, LocalMediaPathSecurityConfig

from .conftest import FakeBrain, web_search_result


@pytest.fixture
def resolver_without_search() -> MediaResolver:
    return MediaResolver(
        path_security=LocalMediaPathSecurity(LocalMediaPathSecurityConfig()),
        brain=None,
    )


class TestLocalResolution:
    def test_resolves_an_allowed_local_file(self, tmp_path: Path) -> None:
        music_dir = tmp_path / "Music"
        music_dir.mkdir()
        song = music_dir / "test.mp3"
        song.touch()

        resolver = MediaResolver(
            path_security=LocalMediaPathSecurity(
                LocalMediaPathSecurityConfig(allowed_roots=(music_dir,))
            )
        )

        source = resolver.resolve(str(song))

        assert source.source_type is MediaSourceType.LOCAL
        assert source.path == str(song.resolve())
        assert source.title == "test.mp3"

    def test_raises_not_found_for_a_missing_local_file(self, tmp_path: Path) -> None:
        music_dir = tmp_path / "Music"
        music_dir.mkdir()

        resolver = MediaResolver(
            path_security=LocalMediaPathSecurity(
                LocalMediaPathSecurityConfig(allowed_roots=(music_dir,))
            )
        )

        with pytest.raises(MediaSourceNotFoundError):
            resolver.resolve(str(music_dir / "missing.mp3"))


class TestUrlResolution:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://m.youtube.com/embed/dQw4w9WgXcQ",
        ],
    )
    def test_recognizes_every_youtube_url_shape(
        self, resolver_without_search: MediaResolver, url: str
    ) -> None:
        source = resolver_without_search.resolve(url)

        assert source.source_type is MediaSourceType.YOUTUBE
        assert source.media_id == "dQw4w9WgXcQ"
        assert source.url == url

    def test_recognizes_a_direct_media_url(self, resolver_without_search: MediaResolver) -> None:
        source = resolver_without_search.resolve("https://example.com/song.mp3")

        assert source.source_type is MediaSourceType.DIRECT_URL
        assert source.url == "https://example.com/song.mp3"
        assert source.mime_type == "audio/mpeg"

    def test_recognizes_a_stream_manifest_url(self, resolver_without_search: MediaResolver) -> None:
        source = resolver_without_search.resolve("https://example.com/live/index.m3u8")

        assert source.source_type is MediaSourceType.STREAM

    def test_rejects_an_arbitrary_webpage_url(self, resolver_without_search: MediaResolver) -> None:
        with pytest.raises(MediaUnsupportedSourceError):
            resolver_without_search.resolve("https://example.com/some/page")

    def test_rejects_empty_query(self, resolver_without_search: MediaResolver) -> None:
        with pytest.raises(MediaValidationError):
            resolver_without_search.resolve("   ")


class TestFreeTextSearchResolution:
    def test_resolves_free_text_via_web_search_to_a_youtube_video(
        self, fake_brain: FakeBrain
    ) -> None:
        fake_brain.queue(
            "web.search",
            web_search_result(
                (
                    {
                        "title": "Imagine Dragons - Believer - YouTube",
                        "url": "https://www.youtube.com/watch?v=7wtfhZwyrcc",
                        "snippet": "Official video",
                    },
                )
            ),
        )

        resolver = MediaResolver(
            path_security=LocalMediaPathSecurity(LocalMediaPathSecurityConfig()),
            brain=fake_brain,  # type: ignore[arg-type]
        )

        source = resolver.resolve("Imagine Dragons Believer")

        assert source.source_type is MediaSourceType.YOUTUBE
        assert source.media_id == "7wtfhZwyrcc"
        assert source.title == "Imagine Dragons - Believer"

    def test_skips_non_youtube_results_and_uses_the_first_youtube_match(
        self, fake_brain: FakeBrain
    ) -> None:
        fake_brain.queue(
            "web.search",
            web_search_result(
                (
                    {"title": "Lyrics site", "url": "https://example.com/lyrics"},
                    {
                        "title": "A South Indian Movie - YouTube",
                        "url": "https://youtu.be/abc123XYZaa",
                    },
                )
            ),
        )

        resolver = MediaResolver(
            path_security=LocalMediaPathSecurity(LocalMediaPathSecurityConfig()),
            brain=fake_brain,  # type: ignore[arg-type]
        )

        source = resolver.resolve("any south indian movies from youtube")

        assert source.media_id == "abc123XYZaa"

    def test_raises_not_found_when_no_result_is_a_youtube_link(
        self, fake_brain: FakeBrain
    ) -> None:
        fake_brain.queue(
            "web.search",
            web_search_result(({"title": "Unrelated", "url": "https://example.com/x"},)),
        )

        resolver = MediaResolver(
            path_security=LocalMediaPathSecurity(LocalMediaPathSecurityConfig()),
            brain=fake_brain,  # type: ignore[arg-type]
        )

        with pytest.raises(MediaSourceNotFoundError):
            resolver.resolve("something obscure")

    def test_raises_not_found_when_no_search_resolver_is_configured(
        self, resolver_without_search: MediaResolver
    ) -> None:
        with pytest.raises(MediaSourceNotFoundError):
            resolver_without_search.resolve("Imagine Dragons Believer")
