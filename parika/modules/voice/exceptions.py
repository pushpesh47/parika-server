"""
PARIKA Voice Module - Exceptions
"""

from __future__ import annotations


class VoiceError(Exception):
    """Base exception for every Voice Module failure."""


class VoiceInputInvalidError(VoiceError):
    """
    Raised when required Tool input is missing/invalid (e.g. neither
    `audio_base64` nor `path` supplied for `speech_to_text`, or an
    empty `text` for `text_to_speech`), or when a referenced input
    file could not be obtained through the existing, unmodified
    `filesystem.read` Capability.
    """


class VoiceWriteError(VoiceError):
    """
    Raised when `text_to_speech` was asked to also persist its result
    (`output_path`) but could not do so through the existing,
    unmodified `filesystem.write` Capability.
    """


class VoiceProviderError(VoiceError):
    """
    Raised when a nested, Provider-backed Voice Goal
    (`voice.provider_speech_to_text`/`voice.provider_text_to_speech`)
    did not succeed (e.g. no compatible local speech engine is
    currently installed/configured).
    """
