"""
PARIKA Document Module - Deterministic Analysis Tool Driver

Implements the `ToolDriver` contract shared by every Analysis
Capability that does *not* require semantic reasoning
(`document.search`, `document.detect_language`,
`document.extract_keywords`, `document.extract_dates`,
`document.extract_contacts`, `document.detect_duplicates`) -- every
one of these is a pure, deterministic text/hash algorithm
(`text_analysis.py`) over the same `UnifiedDocument.text` every other
Tool in this Module obtains through the shared Document Pipeline
(`pipeline.py`). Never a Provider Capability, never a model call --
"local processing first", exactly like `ocr.detect_orientation`/
`ocr.detect_quality` never call a model either.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import text_analysis
from .config import DocumentToolConfig
from .exceptions import DocumentReadError
from .pipeline import resolve_and_parse


class DocumentDeterministicAnalysisToolDriver:
    """
    `ToolDriver` implementing one deterministic Analysis Capability.

    Args:
        kind:
            Which deterministic algorithm this instance runs: one of
            `"search"`, `"detect_language"`, `"extract_keywords"`,
            `"extract_dates"`, `"extract_contacts"`, or
            `"detect_duplicates"`.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        kind: str,
        progress_reporter: ProgressReporter | None = None,
        config: DocumentToolConfig | None = None,
    ) -> None:
        self._brain = brain
        self._kind = kind
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter(f"document.{kind}")
        )
        self._config = config if config is not None else DocumentToolConfig()

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = str(request.arguments.get("path", "")).strip()

        if not path:
            raise DocumentReadError(
                "request.arguments['path'] must be a non-empty string."
            )

        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message=f"Running {self._kind}...")

        try:
            if self._kind == "detect_duplicates":
                result = self._detect_duplicates(request, path, execution_requirements)
            else:
                document = resolve_and_parse(
                    self._brain, path, None, execution_requirements=execution_requirements
                )
                result = self._run(request, document.text)

            self._progress.completed(message="Completed.")

            return ToolResponse(result=result, attributes={"path": path})

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self, request: ToolRequest, text: str) -> dict[str, object]:
        if self._kind == "search":
            return self._search(request, text)

        if self._kind == "detect_language":
            detection = text_analysis.detect_language(text)
            return {
                "detected": detection.detected,
                "language": detection.language,
                "confidence": detection.confidence,
                "candidates": [
                    {"language": candidate.language, "confidence": candidate.confidence}
                    for candidate in detection.candidates
                ],
            }

        if self._kind == "extract_keywords":
            return {
                "keywords": text_analysis.extract_keywords(
                    text, max_keywords=self._config.max_keywords
                )
            }

        if self._kind == "extract_dates":
            return {"dates": text_analysis.extract_dates(text)}

        if self._kind == "extract_contacts":
            return text_analysis.extract_contacts(text)

        raise DocumentReadError(f"Unknown deterministic analysis kind: '{self._kind}'.")

    def _search(self, request: ToolRequest, text: str) -> dict[str, object]:
        query = str(request.arguments.get("query", "")).strip()

        if not query:
            raise DocumentReadError(
                "request.arguments['query'] must be a non-empty string."
            )

        matches = text_analysis.search_text(
            text,
            query,
            case_sensitive=bool(request.arguments.get("case_sensitive", False)),
            use_regex=bool(request.arguments.get("regex", False)),
            context_chars=self._config.search_context_chars,
            max_results=int(request.arguments.get("max_results", 50)),
        )

        return {
            "matches": [
                {"offset": match.offset, "line": match.line, "context": match.context}
                for match in matches
            ],
            "match_count": len(matches),
        }

    def _detect_duplicates(
        self, request: ToolRequest, path: str, execution_requirements: object
    ) -> dict[str, object]:
        other_path = str(request.arguments.get("other_path", "")).strip()

        if not other_path:
            raise DocumentReadError(
                "request.arguments['other_path'] must be a non-empty string."
            )

        document = resolve_and_parse(
            self._brain, path, None, execution_requirements=execution_requirements
        )
        other_document = resolve_and_parse(
            self._brain, other_path, None, execution_requirements=execution_requirements
        )

        comparison = text_analysis.detect_duplicates_pair(document.text, other_document.text)

        return {
            "identical": comparison.identical,
            "similarity": comparison.similarity,
            "other_path": other_path,
        }
