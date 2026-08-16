"""
PARIKA Document Module - Reading Tool Driver

Implements the `ToolDriver` contract shared by every Reading Capability
(`document.extract_text` and the ten `document.read_*` Capabilities),
following exactly the same "one driver class, many parametrized
instances" shape `VisionToolDriver` already establishes
(`parika/modules/vision/driver.py`). All the actual "determine format
-> native parser or OCR fallback -> unified document" logic lives in
`pipeline.py`, shared with `driver_extraction.py` and the Analysis
drivers -- this driver is purely the Tool-facing adapter around it.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from .exceptions import DocumentReadError
from .pipeline import resolve_and_parse


class DocumentReadingToolDriver:
    """
    `ToolDriver` implementing one Reading Capability.

    Args:
        brain:
            Existing, unmodified `Brain` used for every nested Goal
            (`filesystem.read`, and -- for PDFs only -- `ocr.extract_text`).

        expected_format:
            One of `format_detection.SUPPORTED_FORMATS`, fixed at
            construction for every `document.read_*` Capability, or
            `None` for `document.extract_text`, which auto-detects the
            format from the path instead.

        progress_reporter:
            Optional `ProgressReporter` bound to this Tool's own
            Capability id; defaults to a no-op reporter, exactly like
            `OcrToolDriver`/`VisionToolDriver`.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        expected_format: str | None,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._expected_format = expected_format
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter(f"document.read_{expected_format or 'auto'}")
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = str(request.arguments.get("path", "")).strip()

        if not path:
            raise DocumentReadError(
                "request.arguments['path'] must be a non-empty string."
            )

        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Detecting document format...")

        try:
            self._progress.progress(message="Reading document...")

            document = resolve_and_parse(
                self._brain,
                path,
                self._expected_format,
                execution_requirements=execution_requirements,
            )

            self._progress.completed(message="Completed.")

            return ToolResponse(result=document.to_result_dict(), attributes={"path": path})

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise
