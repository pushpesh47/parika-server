"""
PARIKA Generation Module - Shared Goal-Based Engine

Pure orchestration helpers reused by every `image.*`/`video.*`
generation ToolDriver in this Module: obtaining input image/video
bytes through the existing, unmodified `filesystem.read` Capability,
writing a produced artifact back out through `filesystem.write`, and
invoking this Module's own Provider-backed generation Capabilities
through the existing Model Selection Framework -- exactly the same
nested-`Goal`-via-`Brain.handle()` shape `vision/engine.py` and
`video/engine.py` already establish. Introduces no new execution
architecture. No ComfyUI-specific concept exists anywhere in this
module: the nested Goal's `provider_request_builder` returns a
provider-independent `GenerationRequest`, and the result consumed
back is a provider-independent `GenerationResult` -- whichever
Provider Planner's Model Selection Framework actually resolves the
Goal to.
"""

from __future__ import annotations

import base64
from uuid import uuid4

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.goal_result import GoalResult
from parika.core.capability_resolver.capability_resolution import (
    CapabilityResolution,
)
from parika.core.planner.goal import Goal
from parika.core.provider_manager.generation_request import (
    GenerationOperation,
    GenerationRequest,
)
from parika.core.provider_manager.generation_result import GenerationResult
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest

from .exceptions import (
    GenerationInputReadError,
    GenerationProviderError,
    GenerationWriteError,
)

FILESYSTEM_READ_CAPABILITY_ID = "filesystem.read"
FILESYSTEM_WRITE_CAPABILITY_ID = "filesystem.write"


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


def read_file_base64(brain: Brain, path: str) -> str:
    """
    Obtain `path`'s raw bytes, base64-encoded, exclusively through the
    existing, unmodified `filesystem.read` Capability -- the same
    Capability, Tool, security, and permission path every other
    caller (Vision, Video, OCR, Document) already uses. Never touches
    the filesystem directly.
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
        raise GenerationInputReadError(
            f"Could not read file at '{path}'" + (f": {reason}" if reason else ".")
        )

    return str(payload["content_base64"])


def write_file_base64(brain: Brain, path: str, content_base64: str) -> dict:
    """
    Persist `content_base64` to `path` exclusively through the
    existing, unmodified `filesystem.write` Capability. Never touches
    the filesystem directly.
    """

    goal = Goal(
        id=uuid4().hex,
        capability_id=FILESYSTEM_WRITE_CAPABILITY_ID,
        inputs={"path": path, "binary": True, "content_base64": content_base64},
    )

    response = brain.handle(BrainRequest(goals=(goal,)))
    goal_result = response.results[0] if response.results else None
    payload = _tool_result_payload(goal_result)

    if not isinstance(payload, dict):
        reason = _failure_reason(goal_result)
        raise GenerationWriteError(
            f"Could not write artifact to '{path}'"
            + (f": {reason}" if reason else ".")
        )

    return payload


_EXTENSION_BY_MIME_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/webm": "webm",
}


def extension_for_mime_type(mime_type: str, *, default: str = "bin") -> str:
    """
    Map an artifact's provider-independent `mime_type` to a filename
    extension, for building a default `output_path` when the caller
    did not supply one.
    """

    return _EXTENSION_BY_MIME_TYPE.get(mime_type, default)


def generate_with_provider(
    brain: Brain,
    provider_capability_id: str,
    *,
    operation: GenerationOperation,
    task_category: str,
    prompt: str,
    negative_prompt: str = "",
    input_images: tuple[str, ...] = (),
    width: int | None = None,
    height: int | None = None,
    duration_seconds: float | None = None,
    fps: float | None = None,
    seed: int | None = None,
    execution_requirements: object = None,
) -> GenerationResult:
    """
    Execute one generative media operation by constructing a
    Provider-backed nested Goal targeting `provider_capability_id`
    (`CapabilityCategory.IMAGE_GENERATION`/`VIDEO_GENERATION`) --
    resolved, selected, and executed entirely by the existing,
    unmodified Planner/Model Selection Framework/Provider abstraction,
    exactly like `vision.engine.analyze_with_provider()`'s role for
    Vision's Provider Capabilities.

    `task_category` (e.g. `"image_generation"`, `"image_editing"`,
    `"video_generation"`, `"video_generation_from_image"`,
    `"video_editing"`) is threaded into `Goal.metadata
    ["execution_requirements"]["task_category"]` -- the existing,
    unmodified Task Classification override mechanism
    (`parika/core/planner/model_selection/task_classification.py`) --
    so Model Selection's specialization filtering can distinguish
    between operations that share one `CapabilityCategory` (e.g.
    `video_generate_from_image`/`video_edit` both being
    `CapabilityCategory.VIDEO_GENERATION`, but only ever satisfiable
    by a Provider model that actually declares the corresponding
    `ProviderModel.specializations` tag). A caller-supplied
    `execution_requirements` override (already an `ExecutionRequirements`
    instance, or a mapping that itself sets `"task_category"`) always
    takes precedence, exactly as `build_execution_requirements()`
    already documents.

    Returns:
        The provider-independent `GenerationResult`.

    Raises:
        GenerationProviderError:
            If the nested Goal did not succeed (e.g. no compatible
            generation Provider model is currently available).
    """

    def _build_generation_request(
        resolution: CapabilityResolution,
        model: ProviderModel,
    ) -> ProviderRequest:
        return GenerationRequest(
            operation=operation,
            prompt=prompt,
            negative_prompt=negative_prompt,
            input_images=input_images,
            width=width,
            height=height,
            duration_seconds=duration_seconds,
            fps=fps,
            seed=seed,
        )

    goal = Goal(
        id=uuid4().hex,
        capability_id=provider_capability_id,
        inputs={"prompt": prompt},
        provider_request_builder=_build_generation_request,
        metadata={
            "execution_requirements": _merge_task_category(
                execution_requirements, task_category
            )
        },
    )

    response = brain.handle(BrainRequest(goals=(goal,)))
    goal_result = response.results[0] if response.results else None

    if (
        goal_result is None
        or not goal_result.succeeded
        or goal_result.response is None
    ):
        reason = _failure_reason(goal_result)
        raise GenerationProviderError(
            "Generation did not succeed" + (f": {reason}" if reason else ".")
        )

    backend_response = goal_result.response.outputs.get("result")

    if isinstance(backend_response, GenerationResult):
        return backend_response

    raise GenerationProviderError(
        "Generation Provider returned an unexpected result type "
        f"({type(backend_response).__name__})."
    )


def _merge_task_category(execution_requirements: object, task_category: str) -> object:
    """
    Merge this call's default `task_category` into a caller-supplied
    `execution_requirements` override, without overriding an explicit
    `task_category` the caller already set.

    Returns `execution_requirements` unchanged when it is already an
    `ExecutionRequirements` instance (a fully-formed override always
    wins, exactly like `build_execution_requirements()`'s own
    documented precedence).
    """

    from parika.core.planner.model_selection.requirements import (
        ExecutionRequirements,
    )

    if isinstance(execution_requirements, ExecutionRequirements):
        return execution_requirements

    if isinstance(execution_requirements, dict):
        merged = dict(execution_requirements)
        merged.setdefault("task_category", task_category)
        return merged

    return {"task_category": task_category}


def decode_base64(content_base64: str) -> bytes:
    """Decode a base64 artifact payload to raw bytes."""

    return base64.b64decode(content_base64)
