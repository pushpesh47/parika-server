"""
PARIKA Document Module - Shared Provider/Brain Primitives

The nested-Goal steps every Document Module ToolDriver needs, mirroring
exactly `parika/modules/ocr/engine.py`'s own shape:

- `read_document_text()`/`read_document_bytes()` -- obtain a file's
  content through the existing, unmodified `filesystem.read`
  Capability. Never touches the filesystem directly.
- `ocr_extract_text()` -- delegate to the existing, unmodified,
  Tool-backed `ocr.extract_text` Capability (never a new Provider
  Capability, never a re-implementation of OCR) for scanned/image-only
  PDFs and any other content this Module cannot extract text from
  deterministically. This is the Module's *only* path to OCR -- it
  never renders pages, decodes images, or calls a Vision/OCR Provider
  model itself.
- `analyze_content()` -- the one shared nested Goal every semantic
  (Provider-backed) Tool in this Module uses
  (`document.provider_analyze_content`), exactly mirroring
  `ocr.provider_extract_text`/`vision.provider_*`'s own single-
  shared-capability, instruction-parameterized shape.

None of these functions implement filesystem logic, OCR/image
handling, or Provider wire-format serialization themselves -- every
one of those responsibilities stays exactly where it already lives
(the Filesystem Tool, the OCR Module, and the selected Provider's own
driver, respectively): `analyze_content()` builds only the
provider-independent `ChatMessage` (`parika/core/provider_manager
/chat_message.py`).
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

from .exceptions import DocumentAnalysisError, DocumentOcrFallbackError, DocumentReadError

FILESYSTEM_READ_CAPABILITY_ID = "filesystem.read"
OCR_EXTRACT_TEXT_CAPABILITY_ID = "ocr.extract_text"


def read_document_text(brain: Brain, path: str, *, encoding: str = "utf-8") -> str:
    """
    Obtain `path`'s content as decoded text, exclusively through the
    existing, unmodified `filesystem.read` Capability -- used for
    text-native formats (txt, markdown, html, csv, json, xml).
    """

    goal = Goal(
        id=uuid4().hex,
        capability_id=FILESYSTEM_READ_CAPABILITY_ID,
        inputs={"path": path, "binary": False, "encoding": encoding},
    )

    goal_result = _handle_single_goal(brain, goal)
    payload = _tool_result_payload(goal_result)

    if not isinstance(payload, dict) or "content" not in payload:
        reason = _failure_reason(goal_result)
        raise DocumentReadError(
            f"Could not read document at '{path}'" + (f": {reason}" if reason else ".")
        )

    return str(payload["content"])


def read_document_bytes(brain: Brain, path: str) -> bytes:
    """
    Obtain `path`'s raw bytes, exclusively through the existing,
    unmodified `filesystem.read` Capability -- used for binary formats
    (pdf, docx, pptx, xlsx).
    """

    import base64

    goal = Goal(
        id=uuid4().hex,
        capability_id=FILESYSTEM_READ_CAPABILITY_ID,
        inputs={"path": path, "binary": True},
    )

    goal_result = _handle_single_goal(brain, goal)
    payload = _tool_result_payload(goal_result)

    if not isinstance(payload, dict) or "content_base64" not in payload:
        reason = _failure_reason(goal_result)
        raise DocumentReadError(
            f"Could not read document at '{path}'" + (f": {reason}" if reason else ".")
        )

    return base64.b64decode(str(payload["content_base64"]))


def ocr_extract_text(
    brain: Brain,
    path: str,
    *,
    execution_requirements: object = None,
) -> dict:
    """
    Delegate text extraction for `path` entirely to the existing,
    unmodified, Tool-backed `ocr.extract_text` Capability -- the
    Document Module's only path to OCR. Reused verbatim: this Module
    never performs OCR itself, never renders PDF pages, and never
    calls a Vision/OCR Provider model directly (see this module's own
    docstring and `docs/architecture/PARIKA_Core_Coding_Standards.md`'s
    "reuse, never duplicate" principle).

    Returns the raw `ocr.extract_text` result dict, e.g.
    `{"text": ...}` for an image or `{"text": ..., "pages": [...]}`
    for a PDF -- callers adapt this into a `UnifiedDocument`
    themselves (see `readers.read_pdf()`).
    """

    goal = Goal(
        id=uuid4().hex,
        capability_id=OCR_EXTRACT_TEXT_CAPABILITY_ID,
        inputs={"path": path},
        metadata=(
            {"execution_requirements": execution_requirements}
            if execution_requirements is not None
            else {}
        ),
    )

    goal_result = _handle_single_goal(brain, goal)
    payload = _tool_result_payload(goal_result)

    if not isinstance(payload, dict):
        reason = _failure_reason(goal_result)
        raise DocumentOcrFallbackError(
            "OCR fallback did not succeed" + (f": {reason}" if reason else ".")
        )

    return payload


def analyze_content(
    brain: Brain,
    provider_capability_id: str,
    instruction: str,
    content: str,
    *,
    execution_requirements: object = None,
) -> str:
    """
    Analyze `content` (already-extracted document text) by
    constructing a Provider-backed nested Goal targeting
    `provider_capability_id` (e.g.
    `document.provider_analyze_content`, `CapabilityCategory.LLM`) --
    resolved, selected, and executed entirely by the existing,
    unmodified Planner/Model Selection Framework/Provider abstraction,
    exactly like `ocr.engine.recognize_text()` does for
    `ocr.provider_extract_text` and `VisionToolDriver._analyze()` does
    for every `vision.provider_*` Capability -- just with a plain-text
    message instead of an image-bearing one.
    """

    def _build_analysis_request(
        resolution: CapabilityResolution,
        model: ProviderModel,
    ) -> ProviderRequest:
        return ChatRequest(
            messages=(
                ChatMessage(
                    role="user",
                    content=f"{instruction}\n\n---\n\n{content}",
                ),
            ),
        )

    goal = Goal(
        id=uuid4().hex,
        capability_id=provider_capability_id,
        inputs={"instruction": instruction},
        provider_request_builder=_build_analysis_request,
        metadata=(
            {"execution_requirements": execution_requirements}
            if execution_requirements is not None
            else {}
        ),
    )

    goal_result = _handle_single_goal(brain, goal)

    if (
        goal_result is None
        or not goal_result.succeeded
        or goal_result.response is None
    ):
        reason = _failure_reason(goal_result)
        raise DocumentAnalysisError(
            "Document analysis did not succeed" + (f": {reason}" if reason else ".")
        )

    backend_response = goal_result.response.outputs.get("result")

    if isinstance(backend_response, ChatResult):
        return backend_response.message.content

    return str(backend_response)


# ----------------------------------------------------------------------
# Internal
# ----------------------------------------------------------------------


def _handle_single_goal(brain: Brain, goal: Goal) -> GoalResult | None:
    response = brain.handle(BrainRequest(goals=(goal,)))
    return response.results[0] if response.results else None


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
