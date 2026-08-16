"""
PARIKA Video Module - Exceptions
"""

from __future__ import annotations


class VideoError(Exception):
    """Base exception for every Video Module failure."""


class VideoReadError(VideoError):
    """
    Raised when the referenced video could not be validated through
    the existing, unmodified `filesystem.info` Capability (e.g. the
    path does not exist or is not a file), or when a required Tool
    argument (e.g. `path`) was missing.
    """


class VideoDependencyUnavailableError(VideoError):
    """
    Raised when a deterministic Video feature's optional dependency
    (the `video` extra: `opencv-python-headless`, shared with the
    Vision Module's own `vision` extra) is not installed.
    """


class VideoDecodeError(VideoError):
    """
    Raised when an opened video file cannot be decoded (corrupted
    container, unsupported/missing codec, unreadable stream).
    """


class VideoFrameExtractionError(VideoError):
    """
    Raised when a specific frame could not be seeked to/decoded even
    though the video container itself opened successfully.
    """


class VideoAnalysisError(VideoError):
    """
    Raised when a nested, Provider-backed Goal (this Module's own
    `video.provider_*` Capability, or a sibling Module's Provider
    Capability reused directly -- `vision.provider_describe_image`,
    `vision.provider_detect_objects`, `ocr.provider_extract_text`)
    did not succeed.
    """
