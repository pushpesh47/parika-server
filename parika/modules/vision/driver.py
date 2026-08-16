"""
PARIKA Vision Module - Driver

Implements the `ToolDriver` contract shared by every `vision.*`
TOOL-category Capability (`vision.describe_image`,
`vision.answer_question`, `vision.detect_objects`,
`vision.analyze_scene`, `vision.analyze_ui`, `vision.analyze_chart`,
`vision.analyze_diagram`), following exactly the same shape
`OcrToolDriver` already establishes for `ocr.extract_text`
(`parika/modules/ocr/driver.py`), itself mirroring
`CodingAgentToolDriver`/`StandardCodingAgent`
(`parika/modules/coding_agent/driver.py`,
`parika/modules/coding_agent/standard_agent.py`):

    1. Obtain the referenced image through the existing, unmodified,
       permission-protected `filesystem.read` Capability -- by
       constructing a `Goal(capability_id="filesystem.read", ...)` and
       calling `Brain.handle()`, never by reading the file itself and
       never by bypassing `ToolManager`/`WorkspacePermissionManager`.
    2. Analyze the image through the existing Model Selection
       Framework's PROVIDER execution backend -- by constructing a
       second `Goal(capability_id=<its own vision.* provider
       capability>, ...)` with its own `provider_request_builder`,
       exactly like `OcrToolDriver._recognize()` already does for
       `ocr.provider_extract_text`.

One `VisionToolDriver` instance is constructed per TOOL capability
(each bound to its own provider capability id and default
instruction, see `module_driver.py`'s `_VISION_TOOL_SPECS`), rather
than one instance per Capability having its own dedicated class --
purely a code-reuse choice, not a difference in shape: every instance
still implements exactly the same two-step orchestration
`OcrToolDriver` does, satisfying exactly one Tool.

`VisionToolDriver` never implements filesystem logic, image decoding,
or Provider wire-format serialization itself -- every one of those
responsibilities stays exactly where it already lives (the Filesystem
Tool, and the selected Provider's own driver, respectively): this
driver builds only the provider-independent `ChatMessage.images`
field (`parika/core/provider_manager/chat_message.py`).
"""

from __future__ import annotations

from uuid import uuid4

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.goal_result import GoalResult
from parika.core.capability_resolver.capability_resolution import (
    CapabilityResolution,
)
from parika.core.planner.goal import Goal
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from .exceptions import VisionAnalysisError, VisionImageReadError

FILESYSTEM_READ_CAPABILITY_ID = "filesystem.read"


class VisionToolDriver:
    """
    `ToolDriver` implementing one `vision.*` TOOL Capability.

    Args:
        brain:
            Existing, unmodified `Brain` used to submit both nested
            Goals (`filesystem.read`, then this driver's own
            `provider_capability_id`).

        provider_capability_id:
            The internal, Provider-backed Vision Capability id this
            Tool orchestrates (e.g. `"vision.provider_describe_image"`).

        default_instruction:
            Instruction sent to the Vision model when the Tool
            request supplies no explicit `instruction` (ignored when
            `question_argument` is set, since `question` is required
            in that case instead).

        question_argument:
            When `True` (only `vision.answer_question`), the Tool
            requires a non-empty `question` argument instead of an
            optional `instruction` one, and uses it verbatim as the
            instruction sent to the Vision model.

        progress_reporter:
            Optional `ProgressReporter` bound to this Tool's own
            Capability id; defaults to a no-op reporter, exactly like
            `OcrToolDriver`.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        provider_capability_id: str,
        default_instruction: str = "",
        question_argument: bool = False,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._default_instruction = default_instruction
        self._question_argument = question_argument
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter(provider_capability_id)
        )

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = str(request.arguments.get("path", "")).strip()

        if not path:
            raise VisionImageReadError(
                "request.arguments['path'] must be a non-empty string."
            )

        instruction = self._resolve_instruction(request)

        self._progress.started(message="Reading image...")

        image_base64 = self._read_image(path)

        self._progress.progress(message="Waiting for Vision model...")

        text = self._analyze(
            image_base64,
            instruction,
            execution_requirements=request.metadata.get("execution_requirements"),
        )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"text": text},
            attributes={"path": path},
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_instruction(self, request: ToolRequest) -> str:
        if self._question_argument:
            question = str(request.arguments.get("question", "")).strip()

            if not question:
                raise VisionImageReadError(
                    "request.arguments['question'] must be a "
                    "non-empty string."
                )

            return question

        return (
            str(request.arguments.get("instruction", "")).strip()
            or self._default_instruction
        )

    def _read_image(self, path: str) -> str:
        """
        Obtain `path`'s raw bytes, base64-encoded, exclusively through
        the existing, unmodified `filesystem.read` Capability -- the
        same Capability, Tool, security, and permission path every
        other caller (including the model's own direct tool calls)
        already uses. Never touches the filesystem directly.
        """

        goal = Goal(
            id=uuid4().hex,
            capability_id=FILESYSTEM_READ_CAPABILITY_ID,
            inputs={"path": path, "binary": True},
        )

        response = self._brain.handle(BrainRequest(goals=(goal,)))
        goal_result = response.results[0] if response.results else None

        payload = _tool_result_payload(goal_result)

        if not isinstance(payload, dict) or "content_base64" not in payload:
            reason = _failure_reason(goal_result)
            raise VisionImageReadError(
                f"Could not read image at '{path}'"
                + (f": {reason}" if reason else ".")
            )

        return str(payload["content_base64"])

    def _analyze(
        self,
        image_base64: str,
        instruction: str,
        *,
        execution_requirements: object = None,
    ) -> str:
        """
        Analyze `image_base64` by constructing a Provider-backed
        nested Goal targeting this driver's own
        `provider_capability_id` (`CapabilityCategory.VISION`) --
        resolved, selected, and executed entirely by the existing,
        unmodified Planner/Model Selection Framework/Provider
        abstraction, exactly like `OcrToolDriver._recognize()` already
        does for `ocr.provider_extract_text`.

        Args:
            execution_requirements:
                Optional `Goal.metadata["execution_requirements"]`
                override, forwarded from this Tool's own
                `ToolRequest.metadata` (see `ToolCallResolver
                ._extract_execution_requirements_override()` in
                `parika/providers/ollama/tool_calling.py`, the routing
                model's AI-assisted model-selection guidance for
                *this* call). `None` (the default, and every call
                before this parameter existed) builds the inner Goal
                with no `metadata` at all -- fully backward
                compatible; the Model Selection Framework's existing
                filtering/scoring still performs the actual selection
                either way.
        """

        def _build_vision_request(
            resolution: CapabilityResolution,
            model: ProviderModel,
        ) -> ProviderRequest:
            return ChatRequest(
                messages=(
                    ChatMessage(
                        role="user",
                        content=instruction,
                        images=(image_base64,),
                    ),
                ),
            )

        goal = Goal(
            id=uuid4().hex,
            capability_id=self._provider_capability_id,
            inputs={"instruction": instruction},
            provider_request_builder=_build_vision_request,
            metadata=(
                {"execution_requirements": execution_requirements}
                if execution_requirements is not None
                else {}
            ),
        )

        response = self._brain.handle(BrainRequest(goals=(goal,)))
        goal_result = response.results[0] if response.results else None

        if (
            goal_result is None
            or not goal_result.succeeded
            or goal_result.response is None
        ):
            reason = _failure_reason(goal_result)
            raise VisionAnalysisError(
                "Vision analysis did not succeed"
                + (f": {reason}" if reason else ".")
            )

        backend_response = goal_result.response.outputs.get("result")

        if isinstance(backend_response, ChatResult):
            return backend_response.message.content

        return str(backend_response)


def _tool_result_payload(goal_result: GoalResult | None) -> object | None:
    if (
        goal_result is None
        or not goal_result.succeeded
        or goal_result.response is None
    ):
        return None

    backend_response = goal_result.response.outputs.get("result")

    return getattr(backend_response, "result", None)


def _failure_reason(goal_result: GoalResult | None) -> str:
    if goal_result is None:
        return "no result was produced."

    if goal_result.failure is not None:
        return str(goal_result.failure)

    if goal_result.skip_reason is not None:
        return goal_result.skip_reason

    return ""
