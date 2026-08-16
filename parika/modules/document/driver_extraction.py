"""
PARIKA Document Module - Extraction Tool Driver

Implements the `ToolDriver` contract shared by every Extraction
Capability (`document.extract_metadata`, `document.extract_images`,
`document.extract_tables`, `document.extract_links`,
`document.extract_headings`, `document.extract_sections`,
`document.extract_references`, `document.extract_attachments`):
obtain the same `UnifiedDocument` every Reading Tool obtains
(`pipeline.parse_document()`), then return only the one requested
facet -- never a new parsing path, never a model call (per the spec's
own "never use an LLM for ... links, headings, page count, images,
tables, document structure" guidance).

One driver class, eight parametrized instances, following exactly the
same shape `DocumentReadingToolDriver`/`VisionToolDriver` establish.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import text_analysis
from .config import DocumentToolConfig
from .document_model import UnifiedDocument
from .engine import read_document_bytes
from .exceptions import DocumentReadError
from .pipeline import resolve_and_parse

_ATTACHMENT_PACKAGE_PREFIXES: dict[str, tuple[str, ...]] = {
    "docx": ("word/embeddings/", "word/media/"),
    "pptx": ("ppt/embeddings/",),
    "xlsx": ("xl/embeddings/",),
}


class DocumentExtractionToolDriver:
    """
    `ToolDriver` implementing one Extraction Capability.

    Args:
        facet:
            Which facet of the parsed `UnifiedDocument` this instance
            returns: one of `"metadata"`, `"images"`, `"tables"`,
            `"links"`, `"headings"`, `"sections"`, `"references"`, or
            `"attachments"`.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        facet: str,
        progress_reporter: ProgressReporter | None = None,
        config: DocumentToolConfig | None = None,
    ) -> None:
        self._brain = brain
        self._facet = facet
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter(f"document.extract_{facet}")
        )
        self._config = config if config is not None else DocumentToolConfig()

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = str(request.arguments.get("path", "")).strip()

        if not path:
            raise DocumentReadError(
                "request.arguments['path'] must be a non-empty string."
            )

        execution_requirements = request.metadata.get("execution_requirements")
        expected_format = request.arguments.get("format")

        self._progress.started(message=f"Extracting {self._facet}...")

        try:
            if self._facet == "attachments":
                result = self._extract_attachments(path)
            else:
                document = resolve_and_parse(
                    self._brain,
                    path,
                    str(expected_format) if expected_format else None,
                    execution_requirements=execution_requirements,
                )
                result = self._extract_facet(document)

            self._progress.completed(message="Completed.")

            return ToolResponse(result=result, attributes={"path": path})

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _extract_facet(self, document: UnifiedDocument) -> dict[str, object]:
        as_dict = document.to_result_dict()

        if self._facet == "metadata":
            return {"format": document.format, **as_dict["metadata"]}

        if self._facet == "images":
            return {"images": as_dict["images"]}

        if self._facet == "tables":
            return {"tables": as_dict["tables"]}

        if self._facet == "links":
            return {"links": as_dict["links"]}

        if self._facet == "headings":
            return {"headings": as_dict["headings"]}

        if self._facet == "sections":
            sections = as_dict["sections"]

            if not sections and document.text.strip():
                sections = [{"heading": None, "text": document.text.strip()}]

            return {"sections": sections}

        if self._facet == "references":
            references = text_analysis.extract_references(
                document.text, max_candidates=self._config.max_reference_candidates
            )
            return {"references": references}

        raise DocumentReadError(f"Unknown extraction facet: '{self._facet}'.")

    def _extract_attachments(self, path: str) -> dict[str, object]:
        """
        List embedded files (objects, media) inside a ZIP-based
        Office Open XML package (DOCX/PPTX/XLSX). Other formats have
        no notion of an "attachment" in this Module's scope and
        report an empty list rather than raising -- a purely
        deterministic ZIP-directory listing, never a model call.
        """

        from . import format_detection

        document_format = format_detection.detect_format_from_path(path)
        prefixes = _ATTACHMENT_PACKAGE_PREFIXES.get(document_format or "", ())

        if not prefixes:
            return {"attachments": []}

        data = read_document_bytes(self._brain, path)

        try:
            with zipfile.ZipFile(BytesIO(data)) as archive:
                attachments = [
                    {"name": name.rsplit("/", 1)[-1], "package_path": name, "size": info.file_size}
                    for name, info in ((name, archive.getinfo(name)) for name in archive.namelist())
                    if any(name.startswith(prefix) for prefix in prefixes)
                    and not name.endswith("/")
                ]
        except zipfile.BadZipFile:
            return {"attachments": []}

        return {"attachments": attachments}
