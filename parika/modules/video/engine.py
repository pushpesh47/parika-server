"""
PARIKA Video Module - Shared Goal-Based Engine

Pure orchestration helpers reused by every `video.*` ToolDriver in
this Module: validating a video path through the existing,
unmodified `filesystem.info` Capability, and invoking both this
Module's own Provider-backed `video.provider_*` Capabilities and --
critically -- *sibling* Modules' own Provider Capabilities directly
(`vision.provider_describe_image`, `vision.provider_detect_objects`,
`ocr.provider_extract_text`), all through the exact same nested-
`Goal`-via-`Brain.handle()` shape `vision/engine.py` and
`ocr/engine.py` already establish. Introduces no new execution
architecture.

Why sibling Modules' *Provider* Capabilities rather than their *Tool*
Capabilities:

Vision's/OCR's own TOOL Capabilities (`vision.describe_image`,
`vision.detect_objects`, `ocr.extract_text`) each accept only a
filesystem `path` argument -- they obtain the image themselves via a
nested `filesystem.read` Goal. A decoded video frame, however, lives
only in memory (extracted via `frame_io.py` from the video container,
never written back out to a file purely to satisfy another Tool's
`path` argument -- that would be wasted I/O and would additionally
require a writable location for a temporary file, which this Module
has no need to assume exists). Every `vision.*`/`ocr.*` TOOL
Capability's own driver, when it already holds an image in memory,
reaches its Provider Capability the exact same way this file does --
see `vision/driver.py`'s own `_analyze()` and `ocr/engine.py`'s own
`recognize_text()`. Targeting `vision.provider_describe_image`
directly is therefore not a shortcut around Vision's architecture; it
*is* Vision's own architecture, reused for an input shape (an
in-memory frame) Vision's Tool-level API was never meant to cover.
The Provider Capability id is still just a plain string resolved
dynamically by Planner at request time -- exactly like Document's
`engine.py` resolving `"ocr.extract_text"` -- so this introduces no
coupling beyond the two Capability ids themselves.

Why `filesystem.info` (not `filesystem.read`) to validate a video
path: unlike a single image, a video container is read by
`cv2.VideoCapture` (see `frame_io.py`'s own docstring) which requires
a real, seekable filesystem path -- there is no supported in-memory-
buffer input for compressed video. `filesystem.info` still goes
through the existing, unmodified permission/security path
(`PathSecurity.resolve()`) and confirms the path exists and is a
file, before `frame_io.py` ever touches it -- the same protection
`filesystem.read` provides, without reading the (potentially very
large) file's full bytes into memory just to discard them.
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

from .exceptions import VideoAnalysisError, VideoReadError

FILESYSTEM_INFO_CAPABILITY_ID = "filesystem.info"

OCR_PROVIDER_EXTRACT_TEXT_CAPABILITY_ID = "ocr.provider_extract_text"
VISION_PROVIDER_DESCRIBE_IMAGE_CAPABILITY_ID = "vision.provider_describe_image"
VISION_PROVIDER_DETECT_OBJECTS_CAPABILITY_ID = "vision.provider_detect_objects"
VISION_PROVIDER_ANALYZE_SCENE_CAPABILITY_ID = "vision.provider_analyze_scene"
VISION_PROVIDER_COMPARE_IMAGES_CAPABILITY_ID = "vision.provider_compare_images"


def _tool_result_payload(goal_result: GoalResult | None) -> object | None:
    if goal_result is None or not goal_result.succeeded or goal_result.response is None:
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


def resolve_video_path(brain: Brain, path: str) -> str:
    """
    Validate `path` through the existing, unmodified `filesystem.info`
    Capability (permission-checked, existence-checked) and return the
    resolved, absolute path string `frame_io.py`'s `cv2.VideoCapture`
    calls may then open directly. Raises `VideoReadError` when the
    path does not exist, is not a file, or the Capability itself is
    unavailable.
    """

    goal = Goal(
        id=uuid4().hex,
        capability_id=FILESYSTEM_INFO_CAPABILITY_ID,
        inputs={"path": path},
    )

    response = brain.handle(BrainRequest(goals=(goal,)))
    goal_result = response.results[0] if response.results else None
    payload = _tool_result_payload(goal_result)

    if not isinstance(payload, dict) or not payload.get("is_file"):
        reason = _failure_reason(goal_result)
        raise VideoReadError(
            f"Could not validate video at '{path}'" + (f": {reason}" if reason else ".")
        )

    return str(payload.get("path", path))


def analyze_frames_with_provider(
    brain: Brain,
    provider_capability_id: str,
    frames_base64: tuple[str, ...],
    instruction: str,
    *,
    execution_requirements: object = None,
) -> str:
    """
    Analyze one or more base64-encoded frames by constructing a
    Provider-backed nested Goal targeting `provider_capability_id`.
    Works identically whether `provider_capability_id` is one of this
    Module's own `video.provider_*` ids or a sibling Module's Provider
    Capability (`vision.provider_*`, `ocr.provider_*`) -- see this
    module's own docstring for why that is architecturally sound.
    Multiple frames are sent in one provider-independent `ChatMessage`
    via its `images` tuple, preserving temporal ordering; the selected
    Provider's driver translates it into its own concrete wire field.
    """

    def _build_request(
        resolution: CapabilityResolution,
        model: ProviderModel,
    ) -> ProviderRequest:
        return ChatRequest(
            messages=(
                ChatMessage(role="user", content=instruction, images=frames_base64),
            ),
        )

    goal = Goal(
        id=uuid4().hex,
        capability_id=provider_capability_id,
        inputs={"instruction": instruction},
        provider_request_builder=_build_request,
        metadata=(
            {"execution_requirements": execution_requirements}
            if execution_requirements is not None
            else {}
        ),
    )

    response = brain.handle(BrainRequest(goals=(goal,)))
    goal_result = response.results[0] if response.results else None

    if goal_result is None or not goal_result.succeeded or goal_result.response is None:
        reason = _failure_reason(goal_result)
        raise VideoAnalysisError(
            "Video analysis did not succeed" + (f": {reason}" if reason else ".")
        )

    backend_response = goal_result.response.outputs.get("result")

    if isinstance(backend_response, ChatResult):
        return backend_response.message.content

    return str(backend_response)


def extract_text_from_frame(
    brain: Brain,
    image_base64: str,
    *,
    instruction: str = "Extract every piece of text visible in this image, verbatim.",
    execution_requirements: object = None,
) -> str:
    """
    Reuse OCR's own `ocr.provider_extract_text` Provider Capability on
    one in-memory frame -- backs `video.extract_text`. Never a second
    OCR implementation; identical Capability, model, and routing OCR's
    own `ocr.extract_text` Tool uses internally
    (`parika/modules/ocr/engine.py`'s `recognize_text()`).
    """

    return analyze_frames_with_provider(
        brain,
        OCR_PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
        (image_base64,),
        instruction,
        execution_requirements=execution_requirements,
    )


def describe_frame(
    brain: Brain,
    image_base64: str,
    instruction: str,
    *,
    execution_requirements: object = None,
) -> str:
    """Reuse Vision's own `vision.provider_describe_image` Capability on one in-memory frame."""

    return analyze_frames_with_provider(
        brain,
        VISION_PROVIDER_DESCRIBE_IMAGE_CAPABILITY_ID,
        (image_base64,),
        instruction,
        execution_requirements=execution_requirements,
    )


def detect_objects_in_frame(
    brain: Brain,
    image_base64: str,
    instruction: str,
    *,
    execution_requirements: object = None,
) -> str:
    """Reuse Vision's own `vision.provider_detect_objects` Capability on one in-memory frame."""

    return analyze_frames_with_provider(
        brain,
        VISION_PROVIDER_DETECT_OBJECTS_CAPABILITY_ID,
        (image_base64,),
        instruction,
        execution_requirements=execution_requirements,
    )
