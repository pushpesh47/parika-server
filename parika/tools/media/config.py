"""
PARIKA Media Tool - Configuration

Typed snapshot of `[media]` in `config/defaults.toml`, following the
Voice Tool's `VoiceToolConfig`/`load_voice_config()` convention
exactly (see `parika/modules/voice/config.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from parika.core.configuration.configuration import Configuration

DEFAULT_ENABLED = True
DEFAULT_ALLOWED_LOCAL_ROOTS: tuple[str, ...] = ()
"""
Empty by default - local media (`media.play` with a filesystem path)
is disabled until an operator explicitly configures at least one
trusted root. See `security.py`'s module docstring for why this is
narrower than the Filesystem Tool's own default-open reads.
"""

DEFAULT_YOUTUBE_SEARCH_ENABLED = True
"""
Whether free-text `media.play` queries may fall back to a `web.search`
-based YouTube resolution (see `resolution.py`). Disabling this still
leaves local-path, direct-URL, and YouTube-URL resolution available.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaToolConfig:
    enabled: bool = DEFAULT_ENABLED
    allowed_local_roots: tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_ALLOWED_LOCAL_ROOTS
    )
    youtube_search_enabled: bool = DEFAULT_YOUTUBE_SEARCH_ENABLED


def load_media_config(configuration: Configuration | None) -> MediaToolConfig:
    """
    Build a `MediaToolConfig` from `configuration`, or an all-defaults
    instance when `configuration` is `None`.
    """

    if configuration is None:
        return MediaToolConfig()

    raw_roots = configuration.get(
        "media.allowed_local_roots", list(DEFAULT_ALLOWED_LOCAL_ROOTS)
    )

    return MediaToolConfig(
        enabled=bool(configuration.get("media.enabled", DEFAULT_ENABLED)),
        allowed_local_roots=tuple(raw_roots) if raw_roots else (),
        youtube_search_enabled=bool(
            configuration.get(
                "media.youtube_search_enabled", DEFAULT_YOUTUBE_SEARCH_ENABLED
            )
        ),
    )
