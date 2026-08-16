"""
PARIKA Generation Module - Exceptions
"""

from __future__ import annotations


class GenerationError(Exception):
    """Base exception for every Generation Module failure."""


class GenerationInputReadError(GenerationError):
    """
    Raised when a referenced input image/video could not be obtained
    through the existing, unmodified `filesystem.read` Capability, or
    when a required Tool argument (e.g. `prompt`, `path`) was missing.
    """


class GenerationWriteError(GenerationError):
    """
    Raised when a Tool that produces a new artifact file could not
    persist it through the existing, unmodified `filesystem.write`
    Capability.
    """


class GenerationProviderError(GenerationError):
    """
    Raised when a nested, Provider-backed generation Goal
    (`image.provider_generate`, `image.provider_edit`,
    `video.provider_generate`, `video.provider_generate_from_image`,
    `video.provider_edit`) did not succeed (e.g. no compatible
    generation Provider model is currently available/enabled).
    """
