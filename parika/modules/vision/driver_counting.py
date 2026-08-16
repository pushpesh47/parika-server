"""
PARIKA Vision Module - Counting/Classification Drivers

`VisionCountObjectsToolDriver` (`vision.count_objects`) and
`VisionClassifyImageToolDriver` (`vision.classify_image`) both try a
cheap, deterministic algorithm first (`detectors.count_blobs()`/
`detectors.classify_image_heuristic()`) and only fall back to their
own Provider-backed `vision.provider_*` Capability
(`engine.analyze_with_provider()`) when the deterministic result is
not trustworthy for the request at hand:

- Counting: `count_blobs()` is a real connected-component count, but
  only meaningful for simple, high-contrast, uniform-background
  scenes (`BlobCountResult.is_confident`); the moment the caller asks
  to count a *specific kind* of object (`instruction` supplied) --
  which requires recognizing what something *is*, not merely that it
  is a separate blob -- or the blob heuristic itself is not
  confident, this driver falls back to a Provider-backed Vision
  model, exactly like `vision.detect_objects` already does
  unconditionally (this Capability's entire distinction from
  `vision.detect_objects` is trying the free, deterministic path
  first).
- Classification: `classify_image_heuristic()` only ever produces one
  of four coarse image *types* (screenshot/document/graphic/photo);
  the moment the caller supplies open-set `labels` to classify
  against (which requires genuine semantic recognition), this driver
  defers entirely to the Provider-backed Capability instead.
"""

from __future__ import annotations

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import detectors, engine
from .exceptions import VisionImageReadError

_COUNT_DEFAULT_INSTRUCTION = (
    "Count the objects in this image and report the total number, "
    "plus a breakdown by object type if more than one kind is "
    "present."
)


def _require_path(request: ToolRequest) -> str:
    path = str(request.arguments.get("path", "")).strip()

    if not path:
        raise VisionImageReadError(
            "request.arguments['path'] must be a non-empty string."
        )

    return path


class VisionCountObjectsToolDriver:
    """`ToolDriver` implementing `vision.count_objects`."""

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
            "vision.count_objects"
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        instruction = str(request.arguments.get("instruction", "")).strip()

        self._progress.started(message="Reading image...")

        image_base64 = engine.read_image_base64(self._brain, path)
        image = engine.decode_base64_image(image_base64)

        self._progress.progress(message="Counting objects...")

        blob_result = detectors.count_blobs(image)

        # The deterministic blob count answers "how many separate
        # foreground regions are there", which only means "how many
        # objects" when the caller has not asked to count a specific,
        # named kind of object (that requires recognizing *what*
        # something is, not merely that it is a distinct blob) and
        # the heuristic itself considers the image simple enough to
        # trust.
        if blob_result.is_confident and not instruction:
            self._progress.completed(message="Completed.")

            return ToolResponse(
                result={
                    "count": blob_result.count,
                    "method": "deterministic_blob_count",
                    "regions": [
                        {
                            "x": box.x,
                            "y": box.y,
                            "width": box.width,
                            "height": box.height,
                        }
                        for box in blob_result.regions
                    ],
                },
                attributes={"path": path},
            )

        self._progress.progress(message="Waiting for Vision model...")

        text = engine.analyze_with_provider(
            self._brain,
            self._provider_capability_id,
            (image_base64,),
            instruction or _COUNT_DEFAULT_INSTRUCTION,
            execution_requirements=request.metadata.get("execution_requirements"),
        )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "text": text,
                "method": "vision_model",
                "deterministic_blob_count": blob_result.count,
                "deterministic_count_is_confident": blob_result.is_confident,
            },
            attributes={"path": path},
        )


class VisionClassifyImageToolDriver:
    """`ToolDriver` implementing `vision.classify_image`."""

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
            "vision.classify_image"
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        labels = request.arguments.get("labels")

        self._progress.started(message="Reading image...")

        image_base64 = engine.read_image_base64(self._brain, path)
        image = engine.decode_base64_image(image_base64)

        if isinstance(labels, (list, tuple)) and labels:
            self._progress.progress(message="Waiting for Vision model...")

            label_list = [str(label) for label in labels]
            instruction = (
                "Classify this image into exactly one of the "
                f"following categories: {', '.join(label_list)}. "
                "Respond with the single best-matching category "
                "first, then a brief justification."
            )
            text = engine.analyze_with_provider(
                self._brain,
                self._provider_capability_id,
                (image_base64,),
                instruction,
                execution_requirements=request.metadata.get(
                    "execution_requirements"
                ),
            )

            self._progress.completed(message="Completed.")

            return ToolResponse(
                result={
                    "text": text,
                    "method": "vision_model",
                    "candidate_labels": label_list,
                },
                attributes={"path": path},
            )

        self._progress.progress(message="Classifying image...")

        classification = detectors.classify_image_heuristic(image)

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "label": classification.label,
                "confidence": classification.confidence,
                "scores": classification.scores,
                "method": "deterministic_heuristic",
            },
            attributes={"path": path},
        )
