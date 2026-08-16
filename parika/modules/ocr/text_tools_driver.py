"""
PARIKA OCR Module - Text-Based Tool Drivers

`OcrLayoutToolDriver` (`ocr.extract_layout`) and
`OcrLanguageToolDriver` (`ocr.detect_language`) both accept *either*
an already-known `text` argument *or* a `path` (image/PDF) argument.
When `text` is given - typically because the calling model already
called `ocr.extract_text` earlier in the same turn - both Capabilities
run entirely deterministically, at zero additional model cost: this is
"Make new capabilities composable so higher-level tools can reuse
lower-level outputs" and "avoid duplicate OCR passes" taken literally.
`path` remains a convenience fallback for a caller that does not yet
have any recognized text, at the same one-recognize-call cost
`ocr.extract_text` itself already has.

Each Tool Affordance Contract's own `use_when` text nudges the calling
model toward the zero-cost `text` path when it already has the answer,
using the existing, generic mechanism every other Capability's
contract already relies on (`ai_context/tool_context.py`) - never a
new mechanism.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import language
from .config import OcrToolConfig
from .engine import read_image_base64, recognize_text
from .exceptions import OcrDependencyUnavailableError, OcrImageReadError
from .text_layout import build_text_layout

DEFAULT_LAYOUT_INSTRUCTION = (
    "Extract all readable text from this image, preserving its "
    "original line breaks and paragraph spacing exactly."
)
DEFAULT_LANGUAGE_INSTRUCTION = (
    "Extract all readable text from this image, exactly as written."
)


def _resolve_source_text(
    request: ToolRequest,
    *,
    brain: Brain,
    recognize_capability_id: str,
    default_instruction: str,
    progress: ProgressReporter,
) -> str:
    """
    Resolve the text to analyze: an already-known `text` argument
    (zero cost), or a fresh `filesystem.read` + `ocr.provider_extract_text`
    pair over `path` (one model call, exactly like `ocr.extract_text`).
    """

    text = request.arguments.get("text")

    if isinstance(text, str) and text.strip():
        return text

    path = str(request.arguments.get("path", "")).strip()

    if not path:
        raise OcrImageReadError(
            "request.arguments must include either a non-empty 'text' "
            "or a non-empty 'path'."
        )

    instruction = (
        str(request.arguments.get("instruction", "")).strip()
        or default_instruction
    )
    execution_requirements = request.metadata.get("execution_requirements")

    progress.started(message="Reading image...")
    image_base64 = read_image_base64(brain, path)

    progress.progress(message="Waiting for OCR model...")
    return recognize_text(
        brain,
        recognize_capability_id,
        image_base64,
        instruction,
        execution_requirements=execution_requirements,
    )


class OcrLayoutToolDriver:
    """
    `ToolDriver` implementing `ocr.extract_layout`: deterministic line/
    paragraph/heading segmentation (`text_layout.build_text_layout()`)
    over either already-known or freshly-recognized text.
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
            else NullProgressReporter("ocr.extract_layout")
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        try:
            text = _resolve_source_text(
                request,
                brain=self._brain,
                recognize_capability_id=self._recognize_capability_id,
                default_instruction=DEFAULT_LAYOUT_INSTRUCTION,
                progress=self._progress,
            )

            layout = build_text_layout(text)
            self._progress.completed(message="Completed.")

            return ToolResponse(
                result={
                    "text": text,
                    "lines": list(layout.lines),
                    "paragraphs": list(layout.paragraphs),
                    "headings": list(layout.headings),
                    "reading_order": "top_to_bottom",
                    "line_count": len(layout.lines),
                    "paragraph_count": len(layout.paragraphs),
                    "word_count": layout.word_count,
                    "character_count": layout.character_count,
                },
                attributes={},
            )

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise


class OcrLanguageToolDriver:
    """
    `ToolDriver` implementing `ocr.detect_language`: statistical
    language detection (`language.detect_language()`) over either
    already-known or freshly-recognized text - never a second model
    call to *ask* what language text is in.
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
            else NullProgressReporter("ocr.detect_language")
        )
        self._config = config if config is not None else OcrToolConfig()

    def execute(self, request: ToolRequest) -> ToolResponse:
        if not self._config.language_detection_available:
            raise OcrDependencyUnavailableError(
                "ocr.detect_language requires the optional 'ocr' "
                "dependency group (langdetect) to be installed."
            )

        try:
            text = _resolve_source_text(
                request,
                brain=self._brain,
                recognize_capability_id=self._recognize_capability_id,
                default_instruction=DEFAULT_LANGUAGE_INSTRUCTION,
                progress=self._progress,
            )

            result = language.detect_language(text)
            self._progress.completed(message="Completed.")

            return ToolResponse(
                result={
                    "detected": result.detected,
                    "language": result.language,
                    "confidence": result.confidence,
                    "candidates": [
                        {"language": candidate.language, "confidence": candidate.confidence}
                        for candidate in result.candidates
                    ],
                },
                attributes={},
            )

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise
