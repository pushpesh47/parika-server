"""
PARIKA Media Tool - Resolution

Separates *media intent* (a caller's raw query - a local path, a
direct URL, a YouTube link, or free text like "Imagine Dragons
Believer") from the *resolved, provider-independent `MediaSource`*
`media.play` actually dispatches to the Web Client - see
`docs/architecture/adr/0004-media-capability.md`'s "Media
resolution" decision.

No YouTube-specific search logic is hardcoded into `driver.py`/the
Media Capability itself: free-text resolution is delegated to the
existing, unmodified `web.search` Capability through exactly the same
nested-`Goal`-via-`Brain.handle()` shape
`parika.modules.voice.engine` already establishes for reusing
`filesystem.read`/`filesystem.write` - never a second reasoning path,
never a new HTTP client, never a YouTube Data API key. A YouTube
Data API-backed resolver (or any other provider-specific resolver)
can be added later as an alternative `MediaResolver` without changing
`driver.py` at all, since `driver.py` only depends on this module's
`MediaResolver.resolve()` method, not on how it works internally.
"""

from __future__ import annotations

import mimetypes
from urllib.parse import parse_qs, urlsplit

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.goal_result import GoalResult
from parika.core.planner.goal import Goal
from uuid import uuid4

from .exceptions import (
    MediaSourceNotFoundError,
    MediaUnsupportedSourceError,
    MediaValidationError,
)
from .model import MediaSource, MediaSourceType
from .security import LocalMediaPathSecurity

WEB_SEARCH_CAPABILITY_ID = "web.search"
"""
The existing, unmodified Web Search Capability
(`parika/tools/web_search/manifest.py`), reused - never
reimplemented - for free-text media resolution.
"""

_DIRECT_MEDIA_EXTENSIONS = (
    ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac", ".aac", ".opus",
    ".mp4", ".webm", ".mov", ".mkv", ".m4v",
)
"""
File extensions recognized as a directly-playable media file - see
`MediaSourceType.DIRECT_URL`. Deliberately excludes stream manifest
extensions (`.m3u8`/`.mpd`), which resolve to `MediaSourceType.STREAM`
instead.
"""

_STREAM_MANIFEST_EXTENSIONS = (".m3u8", ".mpd")

_YOUTUBE_HOSTS = (
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
)
_YOUTUBE_SHORT_HOST = "youtu.be"


def _extract_youtube_id(parsed_url) -> str | None:
    """
    Extract a YouTube video id from a `watch`/`shorts`/`embed`
    `youtube.com` URL or a `youtu.be` short link. Returns `None` for
    any other URL - never raises, since a non-YouTube URL is a
    perfectly normal input to this function.
    """

    host = parsed_url.netloc.lower()

    if host == _YOUTUBE_SHORT_HOST:
        video_id = parsed_url.path.strip("/").split("/")[0]
        return video_id or None

    if host not in _YOUTUBE_HOSTS:
        return None

    if parsed_url.path == "/watch":
        query = parse_qs(parsed_url.query)
        values = query.get("v")
        return values[0] if values else None

    for prefix in ("/shorts/", "/embed/", "/live/"):
        if parsed_url.path.startswith(prefix):
            return parsed_url.path[len(prefix):].split("/")[0] or None

    return None


def _looks_like_local_path(query: str) -> bool:
    """
    Heuristically recognizes a filesystem-path-shaped query (never a
    URL): an explicit absolute/home/relative-directory path, or a
    bare path already carrying a recognized media file extension.
    Free text such as "Imagine Dragons Believer" never matches this.
    """

    if "://" in query:
        return False

    if query.startswith(("/", "~", "./", "../")):
        return True

    lowered = query.lower()
    return lowered.endswith(_DIRECT_MEDIA_EXTENSIONS)


def _tool_result_payload(goal_result: GoalResult | None) -> object | None:
    """
    Mirrors `parika.modules.voice.engine._tool_result_payload()`
    exactly: unwraps a Tool-backed nested `Goal`'s result.
    """

    if goal_result is None or not goal_result.succeeded or goal_result.response is None:
        return None

    backend_response = goal_result.response.outputs.get("result")
    return getattr(backend_response, "result", None)


class MediaResolver:
    """
    Resolves a caller-supplied media query into a provider-independent
    `MediaSource`.

    Resolution order: local filesystem path, then direct/YouTube URL
    classification, then (only if `brain` was supplied) a free-text
    `web.search` fallback intended to find a matching YouTube video -
    see this module's own docstring for why that stays a nested Goal
    rather than a hardcoded search client.
    """

    def __init__(
        self,
        *,
        path_security: LocalMediaPathSecurity,
        brain: Brain | None = None,
        allowed_url_schemes: tuple[str, ...] = ("http", "https"),
    ) -> None:
        self._path_security = path_security
        self._brain = brain
        self._allowed_url_schemes = allowed_url_schemes

    def resolve(self, query: str, *, title: str | None = None) -> MediaSource:
        """
        Resolve `query` into a `MediaSource`.

        Args:
            query:
                Raw query text - a local path, a URL, or free text.

            title:
                Optional caller-supplied title override.

        Raises:
            MediaValidationError:
                If `query` is not a non-empty string.

            MediaPathNotAllowedError:
                If `query` is a local path outside
                `[media].allowed_local_roots`.

            MediaSourceNotFoundError:
                If `query` is a local path that does not exist, or
                free text that no `web.search` result could resolve
                to a playable source.

            MediaUnsupportedSourceError:
                If `query` is a URL that is neither a recognized
                YouTube link nor a directly-playable media file (an
                arbitrary webpage URL is never assumed playable - see
                the ADR's "Direct URL media" decision).
        """

        if not isinstance(query, str) or not query.strip():
            raise MediaValidationError("A media query must be a non-empty string.")

        query = query.strip()

        if _looks_like_local_path(query):
            return self._resolve_local(query, title=title)

        parsed = urlsplit(query)

        if parsed.scheme in self._allowed_url_schemes and parsed.netloc:
            return self._resolve_url(query, parsed, title=title)

        return self._resolve_by_search(query)

    def _resolve_local(self, query: str, *, title: str | None) -> MediaSource:
        resolved_path = self._path_security.resolve(query)

        if not resolved_path.is_file():
            raise MediaSourceNotFoundError(
                f"No such local media file: '{resolved_path}'."
            )

        return MediaSource(
            source_type=MediaSourceType.LOCAL,
            path=str(resolved_path),
            title=title or resolved_path.name,
            mime_type=mimetypes.guess_type(resolved_path.name)[0],
        )

    def _resolve_url(self, query: str, parsed, *, title: str | None) -> MediaSource:
        youtube_id = _extract_youtube_id(parsed)

        if youtube_id is not None:
            return MediaSource(
                source_type=MediaSourceType.YOUTUBE,
                url=query,
                media_id=youtube_id,
                title=title,
            )

        lowered_path = parsed.path.lower()

        if lowered_path.endswith(_STREAM_MANIFEST_EXTENSIONS):
            return MediaSource(source_type=MediaSourceType.STREAM, url=query, title=title)

        if lowered_path.endswith(_DIRECT_MEDIA_EXTENSIONS):
            return MediaSource(
                source_type=MediaSourceType.DIRECT_URL,
                url=query,
                title=title,
                mime_type=mimetypes.guess_type(parsed.path)[0],
            )

        raise MediaUnsupportedSourceError(
            f"'{query}' looks like a webpage URL, not a direct playable "
            "media URL (audio/video file) or a recognized YouTube link. "
            "PARIKA never assumes an arbitrary webpage is playable media."
        )

    def _resolve_by_search(self, query: str) -> MediaSource:
        if self._brain is None:
            raise MediaSourceNotFoundError(
                f"Could not resolve '{query}' to a local path or a media "
                "URL, and no search-based resolution is configured."
            )

        goal = Goal(
            id=uuid4().hex,
            capability_id=WEB_SEARCH_CAPABILITY_ID,
            inputs={"query": f"{query} site:youtube.com", "max_results": 5},
        )

        response = self._brain.handle(BrainRequest(goals=(goal,)))
        goal_result = response.results[0] if response.results else None
        payload = _tool_result_payload(goal_result)

        if isinstance(payload, tuple):
            for result in payload:
                if not isinstance(result, dict):
                    continue

                url = result.get("url")

                if not isinstance(url, str):
                    continue

                youtube_id = _extract_youtube_id(urlsplit(url))

                if youtube_id is None:
                    continue

                raw_title = result.get("title")
                title = (
                    raw_title.removesuffix(" - YouTube").strip()
                    if isinstance(raw_title, str)
                    else None
                )

                return MediaSource(
                    source_type=MediaSourceType.YOUTUBE,
                    url=url,
                    media_id=youtube_id,
                    title=title or query,
                )

        raise MediaSourceNotFoundError(
            f"No matching YouTube video was found for '{query}'."
        )
