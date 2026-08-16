"""
PARIKA Document Module - Semantic Analysis Tool Driver

Implements the `ToolDriver` contract shared by every Analysis
Capability that genuinely requires semantic reasoning (`document
.summarize`, `document.answer_question`, `document.compare_documents`,
`document.classify`, `document.detect_document_type`,
`document.extract_entities`, `document.extract_action_items`,
`document.extract_timeline`, `document.translate`) -- exactly the set
the spec's own "Use Ollama only for tasks requiring semantic
reasoning" guidance names. Every one of these Capabilities shares the
*same* Provider Capability (`document.provider_analyze_content`),
differing only in their instruction and input arguments -- mirroring
`ocr.provider_extract_text`'s single-shared-capability precedent and
`VisionToolDriver`'s one-driver-class-many-instances shape exactly.

The document's own content is obtained through the same Document
Pipeline every Reading/Extraction Tool uses (`pipeline.py`) -- never a
second, ad hoc parsing path -- then sent as plain text (never an
image) to the Provider model via `engine.analyze_content()`.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from .engine import analyze_content
from .exceptions import DocumentReadError
from .pipeline import resolve_and_parse


class DocumentAnalysisToolDriver:
    """
    `ToolDriver` implementing one Provider-backed Analysis Capability.

    Args:
        provider_capability_id:
            The shared, internal `document.provider_analyze_content`
            Capability id every instance of this driver targets.

        default_instruction:
            Instruction sent to the model when the Tool request
            supplies no explicit `instruction` (ignored when
            `question_argument`/`target_language_argument` is set).

        question_argument:
            When `True` (only `document.answer_question`), requires a
            non-empty `question` argument used verbatim as the
            instruction.

        target_language_argument:
            When `True` (only `document.translate`), requires a
            non-empty `target_language` argument, used to build the
            translation instruction.

        second_document_argument:
            When `True` (only `document.compare_documents`), requires
            a second, non-empty `other_path` argument; both
            documents' extracted text is sent to the model together.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        provider_capability_id: str,
        default_instruction: str = "",
        question_argument: bool = False,
        target_language_argument: bool = False,
        second_document_argument: bool = False,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._default_instruction = default_instruction
        self._question_argument = question_argument
        self._target_language_argument = target_language_argument
        self._second_document_argument = second_document_argument
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter(provider_capability_id)
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = str(request.arguments.get("path", "")).strip()

        if not path:
            raise DocumentReadError(
                "request.arguments['path'] must be a non-empty string."
            )

        execution_requirements = request.metadata.get("execution_requirements")
        instruction = self._resolve_instruction(request)

        self._progress.started(message="Reading document...")

        try:
            content = self._resolve_content(request, path, execution_requirements)

            self._progress.progress(message="Waiting for the model...")

            text = analyze_content(
                self._brain,
                self._provider_capability_id,
                instruction,
                content,
                execution_requirements=execution_requirements,
            )

            self._progress.completed(message="Completed.")

            return ToolResponse(result={"text": text}, attributes={"path": path})

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_instruction(self, request: ToolRequest) -> str:
        if self._question_argument:
            question = str(request.arguments.get("question", "")).strip()

            if not question:
                raise DocumentReadError(
                    "request.arguments['question'] must be a non-empty string."
                )

            return question

        if self._target_language_argument:
            target_language = str(request.arguments.get("target_language", "")).strip()

            if not target_language:
                raise DocumentReadError(
                    "request.arguments['target_language'] must be a "
                    "non-empty string."
                )

            return (
                f"Translate the following document into {target_language}. "
                "Respond with only the translated text, preserving "
                "paragraph structure."
            )

        return (
            str(request.arguments.get("instruction", "")).strip()
            or self._default_instruction
        )

    def _resolve_content(
        self, request: ToolRequest, path: str, execution_requirements: object
    ) -> str:
        document = resolve_and_parse(
            self._brain, path, None, execution_requirements=execution_requirements
        )

        if not self._second_document_argument:
            return document.text

        other_path = str(request.arguments.get("other_path", "")).strip()

        if not other_path:
            raise DocumentReadError(
                "request.arguments['other_path'] must be a non-empty string."
            )

        other_document = resolve_and_parse(
            self._brain, other_path, None, execution_requirements=execution_requirements
        )

        return (
            f"Document A ({path}):\n{document.text}\n\n"
            f"Document B ({other_path}):\n{other_document.text}"
        )
