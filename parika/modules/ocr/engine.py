"""
PARIKA OCR Module - Shared Provider/Brain Primitives

The two nested-Goal steps every OCR Module ToolDriver needs -
reading a file through the existing, unmodified `filesystem.read`
Capability, and recognizing an image's text through the existing,
unmodified `ocr.provider_extract_text` Provider Capability - extracted once here
so `driver.py`'s `OcrToolDriver`, `text_tools_driver.py`, and
`structured_driver.py` all share exactly one implementation rather
than repeating the same `Goal`/`BrainRequest`/`Brain.handle()` wiring
per Tool. Behavior is unchanged from before this extraction (see
`tests/modules/ocr/test_ocr_tool_driver.py`, which continues to pass
unmodified against `OcrToolDriver`'s own public contract).

Neither function implements filesystem logic, image decoding, or
Provider wire-format serialization itself - every one of those
responsibilities stays exactly where it already lives (the Filesystem
Tool, and the selected Provider's own driver, respectively): these
functions build only the provider-independent `ChatMessage.images`
field (`parika/core/provider_manager/chat_message.py`). Mirrors the
pattern `parika/modules/coding_agent/standard_agent.py`'s
`_submit_decomposition_goal()` already establishes for
`coding.plan_change`.
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

from .exceptions import OcrImageReadError, OcrRecognitionError

FILESYSTEM_READ_CAPABILITY_ID = "filesystem.read"


def read_image_base64(brain: Brain, path: str) -> str:
    """
    Obtain `path`'s raw bytes, base64-encoded, exclusively through
    the existing, unmodified `filesystem.read` Capability - the same
    Capability, Tool, security, and permission path every other
    caller (including the model's own direct tool calls) already
    uses. Never touches the filesystem directly.
    """

    goal = Goal(
        id=uuid4().hex,
        capability_id=FILESYSTEM_READ_CAPABILITY_ID,
        inputs={"path": path, "binary": True},
    )

    response = brain.handle(BrainRequest(goals=(goal,)))
    goal_result = response.results[0] if response.results else None

    payload = _tool_result_payload(goal_result)

    if not isinstance(payload, dict) or "content_base64" not in payload:
        reason = _failure_reason(goal_result)
        raise OcrImageReadError(
            f"Could not read image at '{path}'"
            + (f": {reason}" if reason else ".")
        )

    return str(payload["content_base64"])


def recognize_text(
    brain: Brain,
    recognize_capability_id: str,
    image_base64: str,
    instruction: str,
    *,
    execution_requirements: object = None,
) -> str:
    """
    Recognize `image_base64`'s text by constructing a Provider-backed
    nested Goal targeting `recognize_capability_id` (e.g.
    `ocr.provider_extract_text`, `CapabilityCategory.OCR`) - resolved,
    selected, and executed entirely by the existing, unmodified
    Planner/Model Selection Framework/Provider abstraction.

    Args:
        execution_requirements:
            Optional `Goal.metadata["execution_requirements"]`
            override, forwarded from the calling Tool's own
            `ToolRequest.metadata`. `None` (the default) builds the
            inner Goal with no `metadata` at all - fully backward
            compatible; the Model Selection Framework's existing
            filtering/scoring still performs the actual selection
            either way.
    """

    def _build_recognition_request(
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
        capability_id=recognize_capability_id,
        inputs={"instruction": instruction},
        provider_request_builder=_build_recognition_request,
        metadata=(
            {"execution_requirements": execution_requirements}
            if execution_requirements is not None
            else {}
        ),
    )

    response = brain.handle(BrainRequest(goals=(goal,)))
    goal_result = response.results[0] if response.results else None

    if (
        goal_result is None
        or not goal_result.succeeded
        or goal_result.response is None
    ):
        reason = _failure_reason(goal_result)
        raise OcrRecognitionError(
            "OCR recognition did not succeed"
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
