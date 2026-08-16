"""
PARIKA Vision Module - Exceptions
"""

from __future__ import annotations


class VisionError(Exception):
    """Base exception for every Vision Module failure."""


class VisionImageReadError(VisionError):
    """
    Raised when the referenced image could not be obtained through the
    existing, unmodified `filesystem.read` Capability (e.g. the path
    does not exist, is not readable, or did not return binary
    content), or when a required Tool argument (e.g. `path`, or
    `question` for `vision.answer_question`) was missing.
    """


class VisionAnalysisError(VisionError):
    """
    Raised when a nested, Provider-backed Vision Goal
    (`vision.provider_describe_image`, `vision.provider_answer_question`,
    `vision.provider_detect_objects`, `vision.provider_analyze_scene`,
    `vision.provider_analyze_ui`, `vision.provider_analyze_chart`,
    `vision.provider_analyze_diagram`, or any of the newer
    `vision.provider_*` Capabilities this Module registers) did not
    succeed (e.g. no Vision-capable Provider model is currently
    available/enabled).
    """


class VisionWriteError(VisionError):
    """
    Raised when a Tool that produces a new image file (e.g.
    `vision.crop_image`, `vision.resize_image`) could not persist it
    through the existing, unmodified `filesystem.write` Capability.
    """


class VisionDependencyUnavailableError(VisionError):
    """
    Raised when a deterministic Vision feature's optional dependency
    (the `vision` extra: `opencv-python-headless` for face detection/
    GrabCut background segmentation, `pyzbar` for QR/barcode decoding)
    is not installed. Mirrors `OcrDependencyUnavailableError`
    (`parika/modules/ocr/exceptions.py`) exactly.
    """
