"""
PARIKA Vision Module - Face/QR/Barcode Detection Drivers

`VisionDetectFacesToolDriver` (`vision.detect_faces`),
`VisionDetectQrCodesToolDriver` (`vision.detect_qr_codes`), and
`VisionDetectBarcodesToolDriver` (`vision.detect_barcodes`) each
*always* run their own classical, non-model detector first
(`detectors.detect_faces()`/`detect_qr_codes()`/`detect_barcodes()`)
-- never a Vision Language Model call to locate/decode faces or
codes; a VLM cannot reliably decode a QR/barcode's payload at all,
and a Haar cascade is both cheaper and more precise for face
*location* than a VLM's free-text description would be. Each still
registers its own `vision.provider_*` Capability (per this Module's
frozen naming convention) and dispatches to it -- but only when the
caller supplies a non-empty `instruction`, for a semantic narration
*on top of* the already-deterministic detections (e.g. "describe the
people detected" or "does this look like a legitimate product
barcode"), never to perform the detection/decoding itself.

`vision.detect_logos` is deliberately *not* here: identifying *which*
brand a logo belongs to requires genuine semantic/world knowledge no
classical, non-learned algorithm in this codebase can provide (no
bundled logo database exists, unlike faces/QR/barcodes, each backed
by a real classical detector). It reuses `VisionToolDriver`
unmodified instead, via one more `VisionToolSpec` entry in
`module_driver.py` -- exactly the same "cheapest path" every other
purely Provider-backed Vision Capability already takes.
"""

from __future__ import annotations

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import detectors, engine
from .exceptions import VisionImageReadError


def _require_path(request: ToolRequest) -> str:
    path = str(request.arguments.get("path", "")).strip()

    if not path:
        raise VisionImageReadError(
            "request.arguments['path'] must be a non-empty string."
        )

    return path


class _DeterministicDetectionToolDriver:
    """
    Shared shape for `vision.detect_faces`/`vision.detect_qr_codes`/
    `vision.detect_barcodes`: read the image, run a classical
    detector, optionally narrate the result via the Provider-backed
    Capability when `instruction` is supplied. Subclasses only supply
    `_capability_id`, `_detect()`, and `_to_result()`.
    """

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

    def _detect(self, image):
        raise NotImplementedError

    def _to_result(self, detections) -> dict:
        raise NotImplementedError

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        instruction = str(request.arguments.get("instruction", "")).strip()

        self._progress.started(message="Reading image...")

        try:
            image_base64 = engine.read_image_base64(self._brain, path)
            image = engine.decode_base64_image(image_base64)

            self._progress.progress(message="Detecting...")

            detections = self._detect(image)
            result = self._to_result(detections)

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

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise


class VisionDetectFacesToolDriver(_DeterministicDetectionToolDriver):
    """`ToolDriver` implementing `vision.detect_faces`."""

    _capability_id = "vision.detect_faces"

    def _detect(self, image):
        return detectors.detect_faces(image)

    def _to_result(self, detections) -> dict:
        return {
            "count": len(detections),
            "faces": [
                {"x": face.x, "y": face.y, "width": face.width, "height": face.height}
                for face in detections
            ],
        }


class VisionDetectQrCodesToolDriver(_DeterministicDetectionToolDriver):
    """`ToolDriver` implementing `vision.detect_qr_codes`."""

    _capability_id = "vision.detect_qr_codes"

    def _detect(self, image):
        return detectors.detect_qr_codes(image)

    def _to_result(self, detections) -> dict:
        return {
            "count": len(detections),
            "codes": [
                {
                    "data": code.data,
                    "symbology": code.symbology,
                    "x": code.x,
                    "y": code.y,
                    "width": code.width,
                    "height": code.height,
                }
                for code in detections
            ],
        }


class VisionDetectBarcodesToolDriver(_DeterministicDetectionToolDriver):
    """`ToolDriver` implementing `vision.detect_barcodes`."""

    _capability_id = "vision.detect_barcodes"

    def _detect(self, image):
        return detectors.detect_barcodes(image)

    def _to_result(self, detections) -> dict:
        return {
            "count": len(detections),
            "codes": [
                {
                    "data": code.data,
                    "symbology": code.symbology,
                    "x": code.x,
                    "y": code.y,
                    "width": code.width,
                    "height": code.height,
                }
                for code in detections
            ],
        }
