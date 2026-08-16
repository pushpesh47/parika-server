"""
PARIKA Vision Module - Quality/Blur/Rotation/Anomaly Drivers

`VisionAnalyzeImageQualityToolDriver` (`vision.analyze_image_quality`),
`VisionDetectBlurToolDriver` (`vision.detect_blur`),
`VisionDetectRotationToolDriver` (`vision.detect_rotation`), and
`VisionDetectAnomaliesToolDriver` (`vision.detect_anomalies`) are this
Module's cheapest new Capabilities: each reads the image through the
existing `filesystem.read` Capability and then runs a purely
deterministic algorithm (`quality.py`) -- by default, never a second,
Provider-backed Goal, never a model call of any kind, exactly the
"never call an LLM for rotation detection/blur detection" requirement
OCR's own `analysis_driver.py` already takes literally. Each still
registers its own `vision.provider_*` Capability (per this Module's
frozen naming convention) and dispatches to it -- but strictly as an
opt-in add-on: only when the caller supplies a non-empty
`instruction`, for a semantic narration on top of the already-
computed deterministic metrics (e.g. "explain why this photo scored
low" or "what looks unusual about this image"), never to compute the
metrics themselves.
"""

from __future__ import annotations

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, quality
from .exceptions import VisionImageReadError


def _require_path(request: ToolRequest) -> str:
    path = str(request.arguments.get("path", "")).strip()

    if not path:
        raise VisionImageReadError(
            "request.arguments['path'] must be a non-empty string."
        )

    return path


class _DeterministicAnalysisToolDriver:
    """Shared shape for every deterministic-first quality/anomaly Capability
    in this module -- see this module's own docstring."""

    _capability_id: str

    def __init__(
        self,
        *,
        brain,
        provider_capability_id: str,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._progress = progress_reporter or NullProgressReporter(
            self._capability_id
        )

    def _analyze(self, image) -> dict:
        raise NotImplementedError

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        instruction = str(request.arguments.get("instruction", "")).strip()

        self._progress.started(message="Reading image...")

        image_base64 = engine.read_image_base64(self._brain, path)
        image = engine.decode_base64_image(image_base64)

        self._progress.progress(message="Analyzing...")

        result = self._analyze(image)

        if instruction:
            self._progress.progress(message="Waiting for Vision model...")
            result["explanation"] = engine.analyze_with_provider(
                self._brain,
                self._provider_capability_id,
                (image_base64,),
                instruction,
                execution_requirements=request.metadata.get(
                    "execution_requirements"
                ),
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(result=result, attributes={"path": path})


class VisionAnalyzeImageQualityToolDriver(_DeterministicAnalysisToolDriver):
    """`ToolDriver` implementing `vision.analyze_image_quality`."""

    _capability_id = "vision.analyze_image_quality"

    def _analyze(self, image) -> dict:
        result = quality.compute_quality_score(image)
        return {
            "quality_score": result.score,
            "width": result.width,
            "height": result.height,
            "blur_variance": result.blur_variance,
            "is_blurry": result.is_blurry,
            "contrast": result.contrast,
            "brightness": result.brightness,
            "is_low_resolution": result.is_low_resolution,
            "warnings": list(result.warnings),
        }


class VisionDetectBlurToolDriver(_DeterministicAnalysisToolDriver):
    """`ToolDriver` implementing `vision.detect_blur`."""

    _capability_id = "vision.detect_blur"

    def _analyze(self, image) -> dict:
        result = quality.detect_blur(image)
        return {"variance": result.variance, "is_blurry": result.is_blurry}


class VisionDetectRotationToolDriver(_DeterministicAnalysisToolDriver):
    """`ToolDriver` implementing `vision.detect_rotation`."""

    _capability_id = "vision.detect_rotation"

    def _analyze(self, image) -> dict:
        result = quality.detect_rotation(image)
        return {"rotation_degrees": result.degrees, "confidence": result.confidence}


class VisionDetectAnomaliesToolDriver(_DeterministicAnalysisToolDriver):
    """`ToolDriver` implementing `vision.detect_anomalies`."""

    _capability_id = "vision.detect_anomalies"

    def _analyze(self, image) -> dict:
        result = quality.detect_anomalous_regions(image)
        return {
            "has_anomalies": result.has_anomalies,
            "anomaly_score": result.anomaly_score,
            "regions": [
                {"x": box.x, "y": box.y, "width": box.width, "height": box.height}
                for box in result.regions
            ],
        }
