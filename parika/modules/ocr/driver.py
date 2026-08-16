"""
PARIKA OCR Module - Driver

Implements the `ToolDriver` contract for the single, stable
`tool.ocr_extract_text` Tool (capability `ocr.extract_text`).

`OcrToolDriver` is a pure orchestrator: it never implements filesystem
logic, image decoding, or Provider wire-format serialization itself.
The two Brain-mediated steps - reading the file through the existing
`filesystem.read` Capability, and recognizing text through the
existing `ocr.provider_extract_text` Provider Capability - live in
`engine.py`, shared with every other driver in this Module
(`text_tools_driver.py`, `structured_driver.py`,
`analysis_driver.py`). This extraction is behavior-preserving: see
`tests/modules/ocr/test_ocr_tool_driver.py`, which continues to pass
unmodified against this class's public contract.

Three inputs were added on top of the original, unmodified
`path`/`instruction` shape - each purely additive, so every existing
caller keeps working exactly as before:

- `region`: an optional `{"x", "y", "width", "height"}` pixel
  rectangle. When given (and the optional `ocr` dependency group is
  installed), the image is cropped to it before recognition - fewer
  pixels sent to the Provider model means lower latency/cost for
  region-specific OCR. Silently falls back to the whole image if
  malformed or unavailable, never a hard failure.
- `language`: an optional language hint, folded deterministically
  into the recognition instruction - no extra model call.
- `preprocess`: opt-in (`False` by default, so the original,
  already-verified default path stays byte-for-byte unchanged)
  deterministic preprocessing (`preprocessing.preprocess_for_recognition()`)
  run before recognition: deskew, denoise, contrast, upscale.

`ocr.extract_text` is also transparently PDF-aware: when the resolved
file's bytes are a PDF (sniffed via `pdf_support.is_pdf()`, never by
trusting the `.pdf` extension alone), it is handled page by page
(`pdf_support.render_pdf_pages()`) - each page's already-extractable
text layer is used directly, at zero recognition cost, and only pages
with no usable text layer (scanned/image-only pages) are recognized
through the same Provider-backed step, preserving page numbering in
the response's `pages` list. Passing a PDF was previously undefined/
unusable behavior (a raw PDF byte blob is not a valid image for a
vision model), so no existing caller or test is affected by adding
this branch.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import pdf_support, preprocessing
from .config import OcrToolConfig, imaging_dependency_available
from .engine import FILESYSTEM_READ_CAPABILITY_ID, read_image_base64, recognize_text
from .exceptions import OcrImageReadError

DEFAULT_RECOGNITION_INSTRUCTION = (
    "Extract all readable text from this image, preserving structure "
    "(labels/fields and their values) where possible."
)


class OcrToolDriver:
    """
    `ToolDriver` implementing `ocr.extract_text`.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        recognize_capability_id: str,
        progress_reporter: ProgressReporter | None = None,
        config: OcrToolConfig | None = None,
    ) -> None:
        self._brain = brain
        self._recognize_capability_id = recognize_capability_id
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter("ocr.extract_text")
        )
        self._config = config if config is not None else OcrToolConfig()

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = str(request.arguments.get("path", "")).strip()

        if not path:
            raise OcrImageReadError(
                "request.arguments['path'] must be a non-empty string."
            )

        instruction = self._resolve_instruction(request)
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Reading file...")

        try:
            image_base64 = read_image_base64(self._brain, path)
            raw_bytes = base64.b64decode(image_base64)

            if pdf_support.is_pdf(raw_bytes):
                return self._execute_pdf(
                    raw_bytes,
                    path=path,
                    instruction=instruction,
                    execution_requirements=execution_requirements,
                    request=request,
                )

            image_base64 = (
                self._apply_region(raw_bytes, request.arguments.get("region"))
                or image_base64
            )
            image_base64 = self._apply_preprocessing(raw_bytes, request, image_base64)

            self._progress.progress(message="Waiting for OCR model...")

            text = recognize_text(
                self._brain,
                self._recognize_capability_id,
                image_base64,
                instruction,
                execution_requirements=execution_requirements,
            )

            self._progress.completed(message="Completed.")

            return ToolResponse(
                result={"text": text},
                attributes={"path": path},
            )

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_instruction(self, request: ToolRequest) -> str:
        instruction = (
            str(request.arguments.get("instruction", "")).strip()
            or DEFAULT_RECOGNITION_INSTRUCTION
        )

        language = request.arguments.get("language")

        if isinstance(language, str) and language.strip():
            instruction = (
                f"{instruction} Focus on {language.strip()} text "
                "specifically; transcribe it exactly as written."
            )

        return instruction

    def _apply_region(self, raw_bytes: bytes, region: object) -> str | None:
        """
        Crop to `region` before recognition, when possible. Returns
        `None` (leaving the whole image unchanged) whenever `region`
        is absent, malformed, or the optional imaging dependency is
        unavailable - never a hard failure over an optional, best-
        effort optimization.
        """

        if not isinstance(region, Mapping) or not imaging_dependency_available():
            return None

        try:
            x, y, width, height = (
                int(region["x"]),
                int(region["y"]),
                int(region["width"]),
                int(region["height"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

        image = preprocessing.decode_image(raw_bytes)
        cropped = preprocessing.crop_region(
            image, x=x, y=y, width=width, height=height
        )
        return base64.b64encode(preprocessing.encode_image(cropped)).decode("ascii")

    def _apply_preprocessing(
        self, raw_bytes: bytes, request: ToolRequest, current_image_base64: str
    ) -> str:
        """
        Opt-in (`preprocess=True`) deterministic preprocessing - left
        off by default so the original, already-verified default path
        stays byte-for-byte unchanged.
        """

        if not bool(request.arguments.get("preprocess", False)):
            return current_image_base64

        if not self._config.imaging_available:
            return current_image_base64

        image = preprocessing.decode_image(raw_bytes)
        image, _report = preprocessing.preprocess_for_recognition(
            image,
            max_deskew_angle_degrees=self._config.max_deskew_angle_degrees,
            low_resolution_min_dimension=self._config.low_resolution_min_dimension,
        )
        return base64.b64encode(preprocessing.encode_image(image)).decode("ascii")

    def _execute_pdf(
        self,
        raw_bytes: bytes,
        *,
        path: str,
        instruction: str,
        execution_requirements: object,
        request: ToolRequest,
    ) -> ToolResponse:
        return_images = bool(request.arguments.get("return_images", False))

        pages = pdf_support.render_pdf_pages(
            raw_bytes,
            dpi=self._config.pdf_render_dpi,
            min_text_layer_chars=self._config.pdf_min_text_layer_chars,
        )

        page_results: list[dict[str, Any]] = []
        texts: list[str] = []

        for page in pages:
            if page.has_text_layer:
                page_text = page.text_layer
                source = "text_layer"
            else:
                page_text = self._recognize_pdf_page(
                    page.image, instruction, execution_requirements
                )
                source = "ocr"

            entry: dict[str, Any] = {
                "page": page.page_number,
                "text": page_text,
                "source": source,
            }

            if return_images and page.image is not None:
                entry["image_base64"] = base64.b64encode(
                    preprocessing.encode_image(page.image)
                ).decode("ascii")

            page_results.append(entry)
            texts.append(page_text)

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "text": "\n\n".join(text for text in texts if text),
                "pages": page_results,
            },
            attributes={"path": path, "page_count": len(pages)},
        )

    def _recognize_pdf_page(
        self, image: Any, instruction: str, execution_requirements: object
    ) -> str:
        if image is None:
            return ""

        page_image = image

        if self._config.imaging_available:
            page_image, _report = preprocessing.preprocess_for_recognition(
                page_image,
                max_deskew_angle_degrees=self._config.max_deskew_angle_degrees,
                low_resolution_min_dimension=self._config.low_resolution_min_dimension,
            )

        image_base64 = base64.b64encode(
            preprocessing.encode_image(page_image)
        ).decode("ascii")

        self._progress.progress(message="Waiting for OCR model...")

        return recognize_text(
            self._brain,
            self._recognize_capability_id,
            image_base64,
            instruction,
            execution_requirements=execution_requirements,
        )


__all__ = [
    "DEFAULT_RECOGNITION_INSTRUCTION",
    "FILESYSTEM_READ_CAPABILITY_ID",
    "OcrToolDriver",
]
