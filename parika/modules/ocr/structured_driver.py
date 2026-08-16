"""
PARIKA OCR Module - Structured Extraction Drivers

`OcrTableToolDriver` (`ocr.extract_table`) and `OcrFormToolDriver`
(`ocr.extract_form`) both reuse the *same* `filesystem.read` +
`ocr.provider_extract_text` pair every other Capability in this
Module uses (`engine.py`) - no new Provider Capability is registered
for either of them, since table/form extraction is the same
underlying OCR skill (`required_specializations={"ocr"}`) as
`ocr.extract_text`, just with a different, pre-authored instruction
and a structured-JSON response shape. Registering a separate Provider
Capability per Tool here would be duplicate/overlapping registration
for a selection criterion that would be identical every time.

Table/form field extraction is one of the few places this extension
deliberately *does* call a model
(`recognize_text()`/`ocr.provider_extract_text`) rather than a purely
deterministic algorithm - turning pixels into structured field/row
semantics, without a dedicated table/form-structure-recognition model,
is exactly the "semantic reasoning actually required" case the spec's
own performance guidance carves out. What *is* kept deterministic
throughout: `OcrTableToolDriver`'s table-*region* detection
(`table_detection.detect_table_regions()`, never a model call) and
every driver's structured-JSON parsing
(`document_types.parse_structured_response()`, never a model call).

`document.extract_text` (formerly implemented here as
`OcrDocumentToolDriver`) has moved to the first-class Document Module
(`parika/modules/document/`), which reuses this Module's own
`ocr.extract_text` Capability internally for scanned/image-only PDFs
rather than duplicating any OCR logic.
"""

from __future__ import annotations

import base64

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import preprocessing, table_detection
from .config import OcrToolConfig
from .document_types import parse_structured_response
from .engine import read_image_base64, recognize_text
from .exceptions import OcrImageReadError

TABLE_EXTRACTION_INSTRUCTION = (
    'Extract every table visible in this image as strict JSON: an '
    'array of tables, each {"headers": [...], "rows": [[...], ...]}. '
    "Preserve row/column order exactly as shown. Respond with JSON only."
)
FORM_EXTRACTION_INSTRUCTION = (
    "Extract every labeled field, key-value pair, and checkbox/radio "
    "selection visible in this image as strict JSON: an object mapping "
    "each label to its value (use true/false for checkboxes/radio "
    "buttons). Respond with JSON only."
)


def _require_path(request: ToolRequest) -> str:
    path = str(request.arguments.get("path", "")).strip()

    if not path:
        raise OcrImageReadError(
            "request.arguments['path'] must be a non-empty string."
        )

    return path


def _with_additional_instruction(base_instruction: str, request: ToolRequest) -> str:
    extra = str(request.arguments.get("instruction", "")).strip()

    if not extra:
        return base_instruction

    return f"{base_instruction} Additional guidance: {extra}"


class OcrTableToolDriver:
    """
    `ToolDriver` implementing `ocr.extract_table`.

    Table *region* detection (`table_detected`/`regions`) is always
    deterministic (`table_detection.detect_table_regions()`, never a
    model call); it reliably finds ruled/gridded tables only - see
    that function's own docstring. Table *content* extraction into
    structured rows/columns is a semantic task delegated to
    `ocr.provider_extract_text`, with its JSON response
    deterministically parsed
    (`document_types.parse_structured_response()`), never
    re-interpreted by a second model call.
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
            else NullProgressReporter("ocr.extract_table")
        )
        self._config = config if config is not None else OcrToolConfig()

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        execution_requirements = request.metadata.get("execution_requirements")
        instruction = _with_additional_instruction(
            TABLE_EXTRACTION_INSTRUCTION, request
        )

        self._progress.started(message="Reading image...")

        try:
            image_base64 = read_image_base64(self._brain, path)

            regions = self._detect_regions(image_base64)

            self._progress.progress(message="Waiting for OCR model...")
            raw_text = recognize_text(
                self._brain,
                self._recognize_capability_id,
                image_base64,
                instruction,
                execution_requirements=execution_requirements,
            )

            parsed = parse_structured_response(raw_text)
            self._progress.completed(message="Completed.")

            return ToolResponse(
                result={
                    "table_detected": bool(regions),
                    "regions": [
                        {
                            "x": region.x,
                            "y": region.y,
                            "width": region.width,
                            "height": region.height,
                            "row_lines": list(region.row_lines),
                            "column_lines": list(region.column_lines),
                        }
                        for region in regions
                    ],
                    "data": parsed.data,
                    "parsed": parsed.parsed,
                    "raw_text": parsed.raw_text,
                },
                attributes={"path": path},
            )

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise

    def _detect_regions(self, image_base64: str) -> tuple:
        """
        Best-effort: table-region detection is a bonus deterministic
        signal on top of the always-attempted semantic extraction
        below, never a precondition for it. A format Pillow cannot
        decode (rare, but not impossible for an image a multimodal
        Provider model can still read directly) degrades this one
        signal to "no region found" rather than failing the whole
        Tool call.
        """

        if not self._config.imaging_available:
            return ()

        try:
            raw_bytes = base64.b64decode(image_base64)
            image = preprocessing.decode_image(raw_bytes)
            return table_detection.detect_table_regions(image)
        except Exception:
            return ()


class OcrFormToolDriver:
    """
    `ToolDriver` implementing `ocr.extract_form`: key-value/form-field
    extraction, delegated to `ocr.provider_extract_text` (semantic
    reasoning is genuinely required to interpret field/value/checkbox
    structure), with its JSON response deterministically parsed
    (`document_types.parse_structured_response()`).
    """

    def __init__(
        self,
        *,
        brain: Brain,
        recognize_capability_id: str,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._recognize_capability_id = recognize_capability_id
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter("ocr.extract_form")
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = _require_path(request)
        execution_requirements = request.metadata.get("execution_requirements")
        instruction = _with_additional_instruction(
            FORM_EXTRACTION_INSTRUCTION, request
        )

        self._progress.started(message="Reading image...")

        try:
            image_base64 = read_image_base64(self._brain, path)

            self._progress.progress(message="Waiting for OCR model...")
            raw_text = recognize_text(
                self._brain,
                self._recognize_capability_id,
                image_base64,
                instruction,
                execution_requirements=execution_requirements,
            )

            parsed = parse_structured_response(raw_text)
            self._progress.completed(message="Completed.")

            return ToolResponse(
                result={
                    "data": parsed.data,
                    "parsed": parsed.parsed,
                    "raw_text": parsed.raw_text,
                },
                attributes={"path": path},
            )

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise
