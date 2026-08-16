"""
PARIKA Media Tool - Exceptions

Thin, per-domain exception hierarchy, following every other Tool's
convention (see e.g. `parika/modules/voice/exceptions.py`).
"""

from __future__ import annotations


class MediaError(Exception):
    """Base class for every Media Tool error."""


class MediaValidationError(MediaError):
    """A caller-supplied argument (volume, seek position, ...) is invalid."""


class MediaSourceNotFoundError(MediaError):
    """Resolution could not turn a query into a playable `MediaSource`."""


class MediaUnsupportedSourceError(MediaError):
    """A supplied source/URL cannot be represented by any known `MediaSourceType`."""


class MediaPathNotAllowedError(MediaError):
    """A local path fell outside `[media].allowed_local_roots`."""


class MediaClientUnavailableError(MediaError):
    """
    No Web Client is currently connected over
    `WS /api/v1/ws/media/{client_id}`.

    Raised instead of ever reporting playback as started/changed -
    see `docs/architecture/adr/0004-media-capability.md`'s
    "PARIKA never pretends playback succeeded" decision.
    """
