"""
PARIKA Media Tool - Domain Model

Defines the provider-independent `MediaSource` and `MediaState`
domain objects shared by every `media.*` Capability, the
`WS /api/v1/ws/media/{client_id}` transport, and the future, separate
Web Client. See `docs/architecture/adr/0004-media-capability.md` for
the full rationale.

Neither type ever mentions a specific media provider (YouTube, a
particular CDN, ...) or a specific browser/player implementation
(HTMLMediaElement, Video.js, ...) - see `MediaSourceType` and
`PlaybackStatus` below. PARIKA resolves and represents *what* to play
and *what state it was last reported to be in*; the separate Web
Client decides *how* to actually play it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class MediaSourceType(StrEnum):
    """
    Every kind of media source PARIKA can represent.

    Adding a new member here is a breaking change for every existing
    Web Client (see the ADR's "Compatibility/Versioning" decision);
    prefer teaching an existing type to carry a new optional field
    instead where possible. A Web Client that does not recognize a
    given `type` value must fail clearly rather than guess a
    playback strategy - see `docs/guides/Running.md`'s Media API
    section, "Unknown/future source types".
    """

    LOCAL = "local"
    """A file on the PARIKA server's own filesystem."""

    YOUTUBE = "youtube"
    """
    A YouTube video/short, identified by its video id. The Web
    Client is expected to render this with an official YouTube-
    supported browser integration (e.g. the IFrame Player API) -
    PARIKA never downloads, decodes, or extracts a raw media URL for
    it.
    """

    DIRECT_URL = "direct_url"
    """
    A URL that already points directly at a playable media
    resource (e.g. a `.mp3`/`.mp4` file, or a URL whose response
    reports an audio/video MIME type) - deliberately distinct from an
    arbitrary webpage URL, which is never assumed playable.
    """

    STREAM = "stream"
    """
    A network media stream (e.g. HLS/DASH manifest URL) that is
    neither a single direct file nor a YouTube video. Defined for
    forward compatibility; this increment resolves to it only when a
    caller explicitly supplies a stream URL - see `resolution.py`.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaSource:
    """
    Immutable, provider-independent description of one media item to
    play.

    Exactly the fields relevant to `source_type` are meaningful;
    `__post_init__` enforces the minimum required combination for
    each `MediaSourceType` so an incomplete source can never reach a
    Web Client. All other fields are optional descriptive metadata.
    """

    source_type: MediaSourceType
    url: str | None = None
    """Playable/reference URL. Required for YOUTUBE/DIRECT_URL/STREAM."""

    path: str | None = None
    """Server-side filesystem path. Required for LOCAL only."""

    media_id: str | None = None
    """Provider-native identifier, e.g. a YouTube video id."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration: float | None = None
    """Known duration in seconds, when already known; `None` otherwise."""

    mime_type: str | None = None
    """Best-known MIME type, e.g. `"audio/mpeg"`. Advisory only."""

    def __post_init__(self) -> None:
        """
        Enforce the minimum required fields for `source_type`.

        Raises:
            ValueError:
                If a required field for this `source_type` is
                missing. Callers should treat this exactly like any
                other invalid-input error - `resolution.py`/
                `driver.py` never construct a `MediaSource` from
                unchecked input without catching this.
        """

        if self.source_type is MediaSourceType.LOCAL and not self.path:
            raise ValueError("A local MediaSource requires 'path'.")

        if self.source_type is MediaSourceType.YOUTUBE and (
            not self.url or not self.media_id
        ):
            raise ValueError(
                "A youtube MediaSource requires both 'url' and 'media_id'."
            )

        if self.source_type in (
            MediaSourceType.DIRECT_URL,
            MediaSourceType.STREAM,
        ) and not self.url:
            raise ValueError(
                f"A {self.source_type} MediaSource requires 'url'."
            )

    def to_dict(self) -> dict[str, object]:
        """
        Structured, JSON-serializable representation - the exact
        shape sent to the Web Client as a `media.play` command
        payload's `source`, and returned by `media.get_state`. See
        `docs/guides/Running.md`'s Media API section for the wire
        contract.
        """

        return {
            "type": str(self.source_type),
            "url": self.url,
            "path": self.path,
            "media_id": self.media_id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration": self.duration,
            "mime_type": self.mime_type,
        }


class PlaybackStatus(StrEnum):
    """
    Every playback status a Web Client may report, and PARIKA may
    hold as the last known state.

    PARIKA never transitions a `MediaState` into `PLAYING` on its own
    authority - only an inbound Web Client event does (see
    `state_store.py`). Dispatching a `media.play` command only ever
    moves the locally-held state to `LOADING`.
    """

    IDLE = "idle"
    LOADING = "loading"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    BUFFERING = "buffering"
    ENDED = "ended"
    ERROR = "error"


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaState:
    """
    Immutable snapshot of PARIKA's last known media playback state.

    This is *last known* state, not a live control-plane value: the
    separate Web Client is the sole authority for actual playback
    (see this package's module docstring and the ADR). `position` is
    only ever as fresh as the most recent `media.position_changed`/
    `media.state_changed` event PARIKA received.
    """

    status: PlaybackStatus
    source: MediaSource | None = None
    position: float | None = None
    volume: float = 1.0
    """Linear volume in `[0.0, 1.0]`. `1.0` is unity gain, not amplification."""

    muted: bool = False
    playback_rate: float = 1.0
    visible: bool = False
    """Whether the Web Client currently shows a video surface/UI."""

    client_connected: bool = False
    error_message: str | None = None
    updated_at: datetime = datetime.min.replace(tzinfo=UTC)

    @classmethod
    def initial(cls) -> "MediaState":
        """The state PARIKA holds before any command/event ever occurs."""

        return cls(status=PlaybackStatus.IDLE, updated_at=datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        """
        Structured, JSON-serializable representation, returned by
        `GET /api/v1/media/state` and `media.get_state`.
        """

        return {
            "status": str(self.status),
            "source": self.source.to_dict() if self.source is not None else None,
            "position": self.position,
            "volume": self.volume,
            "muted": self.muted,
            "playback_rate": self.playback_rate,
            "visible": self.visible,
            "client_connected": self.client_connected,
            "error_message": self.error_message,
            "updated_at": self.updated_at.isoformat(),
        }
