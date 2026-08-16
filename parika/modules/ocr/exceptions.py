"""
PARIKA OCR Module - Exceptions
"""

from __future__ import annotations


class OcrError(Exception):
    """Base exception for every OCR Module failure."""


class OcrImageReadError(OcrError):
    """
    Raised when the referenced image could not be obtained through the
    existing, unmodified `filesystem.read` Capability (e.g. the path
    does not exist, is not readable, or did not return binary
    content).
    """


class OcrRecognitionError(OcrError):
    """
    Raised when the nested, Provider-backed `ocr.provider_extract_text`
    Goal did not succeed (e.g. no OCR-capable Provider model is
    currently available/enabled).
    """


class OcrDependencyUnavailableError(OcrError):
    """
    Raised when a deterministic OCR feature (image preprocessing/
    analysis, PDF page rendering, statistical language detection) is
    invoked while its optional dependency group is not installed (see
    `parika/modules/ocr/config.py`).
    `ocr.extract_text`/`ocr.provider_extract_text` themselves never
    raise this - only the deterministic capabilities that depend on
    the optional `ocr` extra (`pyproject.toml`).
    """


class OcrPdfError(OcrError):
    """
    Raised when a referenced PDF file could not be parsed or rendered
    (e.g. it is corrupted, encrypted, or not a valid PDF).
    """
