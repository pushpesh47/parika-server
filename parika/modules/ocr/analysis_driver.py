"""
PARIKA OCR Module - Deterministic Analysis Drivers

`OcrOrientationToolDriver` (`ocr.detect_orientation`) and
`OcrQualityToolDriver` (`ocr.detect_quality`) are the cheapest
Capabilities in this Module: each reads a file through the existing
`filesystem.read` Capability (see `engine.read_image_base64()`) and
then runs a purely deterministic image algorithm
(`image_analysis.py`) - never a second, Provider-backed Goal, never a
model call of any kind. Exactly the
"never call an LLM for rotation detection/blur detection/OCR
confidence" requirement, taken literally: these two Capabilities
cannot reach a model even if asked to.

Both raise `OcrDependencyUnavailableError` up front - before even
reading the file - when the optional `ocr` dependency group (Pillow/
numpy) is not installed, rather than performing a filesystem read
that could never be used.
"""

from __future__ import annotations

import base64

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import image_analysis, preprocessing
from .config import OcrToolConfig
from .engine import read_image_base64
from .exceptions import OcrDependencyUnavailableError, OcrImageReadError


def _require_path(request: ToolRequest) -> str:
    path = str(request.arguments.get("path", "")).strip()

    if not path:
        raise OcrImageReadError(
            "request.arguments['path'] must be a non-empty string."
        )

    return path


class OcrOrientationToolDriver:
    """
    `ToolDriver` implementing `ocr.detect_orientation` - a pure,
    deterministic rotation guess (`image_analysis.detect_orientation()`),
    never a model call.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        progress_reporter: ProgressReporter | None = None,
        config: OcrToolConfig | None = None,
    ) -> None:
        self._brain = brain
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter("ocr.detect_orientation")
        )
        self._config = config if config is not None else OcrToolConfig()

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)

        if not self._config.imaging_available:
            raise OcrDependencyUnavailableError(
                "ocr.detect_orientation requires the optional 'ocr' "
                "dependency group (Pillow, numpy) to be installed."
            )

        self._progress.started(message="Reading image...")

        try:
            raw_bytes = base64.b64decode(read_image_base64(self._brain, path))
            image = preprocessing.decode_image(raw_bytes)
            result = image_analysis.detect_orientation(image, exif_corrected=True)

            self._progress.completed(message="Completed.")

            return ToolResponse(
                result={
                    "rotation_degrees": result.degrees,
                    "confidence": result.confidence,
                    "exif_corrected": result.exif_corrected,
                },
                attributes={"path": path},
            )

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise


class OcrQualityToolDriver:
    """
    `ToolDriver` implementing `ocr.detect_quality` - a pure,
    deterministic document-image quality assessment
    (`image_analysis.compute_quality_score()`), never a model call.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        progress_reporter: ProgressReporter | None = None,
        config: OcrToolConfig | None = None,
    ) -> None:
        self._brain = brain
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter("ocr.detect_quality")
        )
        self._config = config if config is not None else OcrToolConfig()

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)

        if not self._config.imaging_available:
            raise OcrDependencyUnavailableError(
                "ocr.detect_quality requires the optional 'ocr' "
                "dependency group (Pillow, numpy) to be installed."
            )

        self._progress.started(message="Reading image...")

        try:
            raw_bytes = base64.b64decode(read_image_base64(self._brain, path))
            image = preprocessing.decode_image(raw_bytes)
            result = image_analysis.compute_quality_score(
                image,
                blur_threshold=self._config.blur_variance_threshold,
                low_resolution_min_dimension=self._config.low_resolution_min_dimension,
            )

            self._progress.completed(message="Completed.")

            return ToolResponse(
                result={
                    "quality_score": result.score,
                    "meets_minimum_quality": (
                        result.score >= self._config.quality_score_minimum
                    ),
                    "width": result.width,
                    "height": result.height,
                    "is_low_resolution": result.is_low_resolution,
                    "blur_variance": result.blur_variance,
                    "is_blurry": result.is_blurry,
                    "contrast": result.contrast,
                    "brightness": result.brightness,
                    "warnings": list(result.warnings),
                },
                attributes={"path": path},
            )

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise
