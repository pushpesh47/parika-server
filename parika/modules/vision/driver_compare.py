"""
PARIKA Vision Module - Compare/Difference Drivers

`VisionCompareImagesToolDriver` (`vision.compare_images`) and
`VisionDetectDifferencesToolDriver` (`vision.detect_differences`)
both obtain two images through the existing, unmodified
`filesystem.read` Capability (via `engine.read_image_base64()`, twice)
and *always* run a purely deterministic similarity/difference
algorithm first (`hashing.compare_images()`/`hashing.find_diff_regions()`)
-- never a model call for the core metrics themselves. Only when the
caller supplies a non-empty `instruction` (asking for a semantic
explanation of *why* the images differ, which no pixel-level
algorithm can produce) do they additionally construct a Provider-
backed nested Goal against their own `vision.provider_*` Capability
via `engine.analyze_with_provider()`, sending *both* images in one
provider-independent `ChatMessage` (its `images` tuple accepts more
than one). This is the "prefer deterministic... only invoke a Vision
Language Model when semantic interpretation or reasoning is required"
requirement,
applied literally: the deterministic result is always computed and
always returned; the model call is additive and opt-in.
"""

from __future__ import annotations

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, hashing
from .exceptions import VisionImageReadError


def _require_two_paths(request: ToolRequest) -> tuple[str, str]:
    path_a = str(request.arguments.get("path_a", "")).strip()
    path_b = str(request.arguments.get("path_b", "")).strip()

    if not path_a or not path_b:
        raise VisionImageReadError(
            "request.arguments['path_a'] and ['path_b'] must both be "
            "non-empty strings."
        )

    return path_a, path_b


def _instruction(request: ToolRequest) -> str:
    return str(request.arguments.get("instruction", "")).strip()


class VisionCompareImagesToolDriver:
    """`ToolDriver` implementing `vision.compare_images`."""

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
            "vision.compare_images"
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        path_a, path_b = _require_two_paths(request)
        instruction = _instruction(request)

        self._progress.started(message="Reading images...")

        image_a_base64 = engine.read_image_base64(self._brain, path_a)
        image_b_base64 = engine.read_image_base64(self._brain, path_b)

        self._progress.progress(message="Comparing images...")

        image_a = engine.decode_base64_image(image_a_base64)
        image_b = engine.decode_base64_image(image_b_base64)
        comparison = hashing.compare_images(image_a, image_b)

        result: dict = {
            "perceptual_hash_distance": comparison.perceptual_hash_distance,
            "perceptual_hash_similarity": comparison.perceptual_hash_similarity,
            "pixel_similarity": comparison.pixel_similarity,
            "histogram_similarity": comparison.histogram_similarity,
            "overall_similarity": comparison.overall_similarity,
            "same_dimensions": comparison.same_dimensions,
        }

        if instruction:
            self._progress.progress(message="Waiting for Vision model...")
            result["explanation"] = engine.analyze_with_provider(
                self._brain,
                self._provider_capability_id,
                (image_a_base64, image_b_base64),
                instruction,
                execution_requirements=request.metadata.get(
                    "execution_requirements"
                ),
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result=result, attributes={"path_a": path_a, "path_b": path_b}
        )


class VisionDetectDifferencesToolDriver:
    """`ToolDriver` implementing `vision.detect_differences`."""

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
            "vision.detect_differences"
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        path_a, path_b = _require_two_paths(request)
        instruction = _instruction(request)

        self._progress.started(message="Reading images...")

        image_a_base64 = engine.read_image_base64(self._brain, path_a)
        image_b_base64 = engine.read_image_base64(self._brain, path_b)

        self._progress.progress(message="Locating differences...")

        image_a = engine.decode_base64_image(image_a_base64)
        image_b = engine.decode_base64_image(image_b_base64)
        boxes = hashing.find_diff_regions(image_a, image_b)
        ratio = hashing.difference_ratio(image_a, image_b)

        result: dict = {
            "difference_ratio": ratio,
            "region_count": len(boxes),
            "regions": [
                {"x": box.x, "y": box.y, "width": box.width, "height": box.height}
                for box in boxes
            ],
        }

        if instruction:
            self._progress.progress(message="Waiting for Vision model...")
            result["explanation"] = engine.analyze_with_provider(
                self._brain,
                self._provider_capability_id,
                (image_a_base64, image_b_base64),
                instruction,
                execution_requirements=request.metadata.get(
                    "execution_requirements"
                ),
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result=result, attributes={"path_a": path_a, "path_b": path_b}
        )
