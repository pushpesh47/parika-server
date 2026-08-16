"""
PARIKA OCR Module - Configuration

Reads the `[ocr]` configuration section and detects, at runtime,
whether each optional deterministic dependency is installed:
`Pillow`/`numpy` (image preprocessing and analysis), `pypdfium2` (PDF
page rendering and text-layer extraction), and `langdetect`
(statistical language detection). This mirrors exactly the pattern
`parika/tools/coding/config.py` already establishes for the `coding`
extra's `tree-sitter`/`tree-sitter-language-pack` dependency.

`ocr.extract_text`/`ocr.provider_extract_text` never depend on any of this - every
deterministic feature this module adds is purely additive and
gracefully unavailable (never a crash) when the optional `ocr`
dependency group (`pyproject.toml`) is not installed; callers check
the relevant `*_available` property first, exactly like
`CodingToolConfig.tree_sitter_enabled` already does.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

from .exceptions import OcrDependencyUnavailableError

DEFAULT_ENABLED = True
DEFAULT_PREPROCESSING_ENABLED = True
DEFAULT_LANGUAGE_DETECTION_ENABLED = True
DEFAULT_MAX_DESKEW_ANGLE_DEGREES = 15.0
DEFAULT_LOW_RESOLUTION_MIN_DIMENSION = 1000
DEFAULT_BLUR_VARIANCE_THRESHOLD = 100.0
DEFAULT_QUALITY_SCORE_MINIMUM = 0.5
DEFAULT_PDF_RENDER_DPI = 200
DEFAULT_PDF_MIN_TEXT_LAYER_CHARS = 20


def pillow_dependency_available() -> bool:
    """
    Whether the optional `Pillow` dependency (basic image decode/
    encode/crop - no numpy-based analysis) is installed.
    """

    return importlib.util.find_spec("PIL") is not None


def imaging_dependency_available() -> bool:
    """
    Whether the optional `Pillow`/`numpy` pair (the numpy-based
    deterministic image analysis algorithms - orientation, skew,
    blur, quality, table-region detection) is installed.
    """

    return pillow_dependency_available() and importlib.util.find_spec("numpy") is not None


def pdf_dependency_available() -> bool:
    """
    Whether the optional `pypdfium2` dependency (PDF page rendering
    and text-layer extraction) is installed.
    """

    return importlib.util.find_spec("pypdfium2") is not None


def language_detection_dependency_available() -> bool:
    """
    Whether the optional `langdetect` dependency (statistical
    language detection over already-recognized text) is installed.
    """

    return importlib.util.find_spec("langdetect") is not None


def require_pillow() -> None:
    """
    Raise `OcrDependencyUnavailableError` unless the optional `Pillow`
    dependency is installed. Shared by every module in this package
    that needs only basic image decode/encode/crop
    (`preprocessing.py`) - kept here, not in any one of them, so
    `preprocessing.py`, `image_analysis.py`, and `table_detection.py`
    can each depend on it without depending on one another.
    """

    if not pillow_dependency_available():
        raise OcrDependencyUnavailableError(
            "This OCR feature requires the optional 'ocr' dependency "
            "group (Pillow) to be installed."
        )


def require_imaging() -> None:
    """
    Raise `OcrDependencyUnavailableError` unless the optional `Pillow`/
    `numpy` pair is installed. Shared by every module in this package
    that needs numpy-based image analysis (`image_analysis.py`,
    `table_detection.py`) - see `require_pillow()`'s own docstring for
    why this lives here rather than in any one of them.
    """

    if not imaging_dependency_available():
        raise OcrDependencyUnavailableError(
            "This deterministic OCR feature requires the optional "
            "'ocr' dependency group (Pillow, numpy) to be installed."
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OcrToolConfig:
    """
    Immutable, typed snapshot of `[ocr]` configuration.
    """

    enabled: bool = DEFAULT_ENABLED
    preprocessing_enabled: bool = DEFAULT_PREPROCESSING_ENABLED
    language_detection_enabled: bool = DEFAULT_LANGUAGE_DETECTION_ENABLED
    max_deskew_angle_degrees: float = DEFAULT_MAX_DESKEW_ANGLE_DEGREES
    low_resolution_min_dimension: int = DEFAULT_LOW_RESOLUTION_MIN_DIMENSION
    blur_variance_threshold: float = DEFAULT_BLUR_VARIANCE_THRESHOLD
    quality_score_minimum: float = DEFAULT_QUALITY_SCORE_MINIMUM
    pdf_render_dpi: int = DEFAULT_PDF_RENDER_DPI
    pdf_min_text_layer_chars: int = DEFAULT_PDF_MIN_TEXT_LAYER_CHARS

    @property
    def imaging_available(self) -> bool:
        """Whether preprocessing is both enabled and installed."""

        return self.preprocessing_enabled and imaging_dependency_available()

    @property
    def pdf_available(self) -> bool:
        """Whether PDF page rendering/text-layer extraction is installed."""

        return pdf_dependency_available()

    @property
    def language_detection_available(self) -> bool:
        """Whether language detection is both enabled and installed."""

        return self.language_detection_enabled and language_detection_dependency_available()


def load_ocr_config(configuration: Configuration | None) -> OcrToolConfig:
    """
    Build an `OcrToolConfig` snapshot from `Configuration`.
    """

    if configuration is None:
        return OcrToolConfig()

    return OcrToolConfig(
        enabled=bool(configuration.get("ocr.enabled", DEFAULT_ENABLED)),
        preprocessing_enabled=bool(
            configuration.get(
                "ocr.preprocessing_enabled", DEFAULT_PREPROCESSING_ENABLED
            )
        ),
        language_detection_enabled=bool(
            configuration.get(
                "ocr.language_detection_enabled", DEFAULT_LANGUAGE_DETECTION_ENABLED
            )
        ),
        max_deskew_angle_degrees=float(
            configuration.get(
                "ocr.max_deskew_angle_degrees", DEFAULT_MAX_DESKEW_ANGLE_DEGREES
            )
        ),
        low_resolution_min_dimension=int(
            configuration.get(
                "ocr.low_resolution_min_dimension",
                DEFAULT_LOW_RESOLUTION_MIN_DIMENSION,
            )
        ),
        blur_variance_threshold=float(
            configuration.get(
                "ocr.blur_variance_threshold", DEFAULT_BLUR_VARIANCE_THRESHOLD
            )
        ),
        quality_score_minimum=float(
            configuration.get(
                "ocr.quality_score_minimum", DEFAULT_QUALITY_SCORE_MINIMUM
            )
        ),
        pdf_render_dpi=int(
            configuration.get("ocr.pdf_render_dpi", DEFAULT_PDF_RENDER_DPI)
        ),
        pdf_min_text_layer_chars=int(
            configuration.get(
                "ocr.pdf_min_text_layer_chars", DEFAULT_PDF_MIN_TEXT_LAYER_CHARS
            )
        ),
    )
