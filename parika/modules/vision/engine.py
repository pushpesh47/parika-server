"""
PARIKA Vision Module - Shared Goal-Based Engine

Pure orchestration helpers reused by every new `vision.*` ToolDriver
in this Module: obtaining image bytes through the existing,
unmodified `filesystem.read`/`filesystem.list` Capabilities, writing
a produced image back out through `filesystem.write`, and invoking
this Module's own Provider-backed Vision Capabilities (one or more
images per call) through the existing Model Selection Framework.
Exactly the same nested-`Goal`-via-`Brain.handle()` shape
`VisionToolDriver`/OCR's `engine.py` already establish (see
`driver.py`'s own module docstring); introduces no new execution
architecture. Every function here is pure orchestration -- no
algorithm of any kind lives here (see `hashing.py`, `quality.py`,
`detectors.py`, `segmentation.py`, `editing.py` for the deterministic
algorithms themselves).
"""

from __future__ import annotations

import base64
import io
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

from .exceptions import VisionAnalysisError, VisionImageReadError, VisionWriteError

FILESYSTEM_READ_CAPABILITY_ID = "filesystem.read"
FILESYSTEM_WRITE_CAPABILITY_ID = "filesystem.write"
FILESYSTEM_LIST_CAPABILITY_ID = "filesystem.list"

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff")
"""Suffixes treated as images when enumerating a directory without an
explicit `pattern` (`list_image_paths()`)."""


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


def read_image_payload(brain: Brain, path: str) -> dict:
    """
    Obtain `path`'s full `filesystem.read` result payload (including
    `content_base64` and `size`), exclusively through the existing,
    unmodified `filesystem.read` Capability. `read_image_base64()`
    is the common case built on top of this.
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
        raise VisionImageReadError(
            f"Could not read image at '{path}'"
            + (f": {reason}" if reason else ".")
        )

    return payload


def read_image_base64(brain: Brain, path: str) -> str:
    """
    Obtain `path`'s raw bytes, base64-encoded, exclusively through the
    existing, unmodified `filesystem.read` Capability -- the same
    Capability, Tool, security, and permission path every other
    caller already uses. Never touches the filesystem directly.
    Exactly `VisionToolDriver._read_image()`'s own logic, factored out
    so every new driver in this Module shares one implementation
    instead of copying it.
    """

    return str(read_image_payload(brain, path)["content_base64"])


def write_image_base64(brain: Brain, path: str, image_base64: str) -> dict:
    """
    Persist `image_base64` to `path` exclusively through the existing,
    unmodified `filesystem.write` Capability. Used by every editing
    Capability that produces a new image file (`vision.crop_image`,
    `vision.resize_image`, ...). Never touches the filesystem
    directly.
    """

    goal = Goal(
        id=uuid4().hex,
        capability_id=FILESYSTEM_WRITE_CAPABILITY_ID,
        inputs={"path": path, "binary": True, "content_base64": image_base64},
    )

    response = brain.handle(BrainRequest(goals=(goal,)))
    goal_result = response.results[0] if response.results else None
    payload = _tool_result_payload(goal_result)

    if not isinstance(payload, dict):
        reason = _failure_reason(goal_result)
        raise VisionWriteError(
            f"Could not write image to '{path}'"
            + (f": {reason}" if reason else ".")
        )

    return payload


def list_image_paths(
    brain: Brain, directory: str, *, pattern: str | None = None
) -> list[str]:
    """
    Enumerate image file paths under `directory` through the
    existing, unmodified `filesystem.list` Capability, filtering to
    `IMAGE_SUFFIXES` when no explicit glob `pattern` is given. Used by
    the multi-image Capabilities (`vision.find_duplicates`,
    `vision.find_similar_images`, `vision.search_images`) to resolve a
    `directory` argument into concrete paths.
    """

    goal = Goal(
        id=uuid4().hex,
        capability_id=FILESYSTEM_LIST_CAPABILITY_ID,
        inputs={"path": directory, **({"pattern": pattern} if pattern else {})},
    )

    response = brain.handle(BrainRequest(goals=(goal,)))
    goal_result = response.results[0] if response.results else None
    payload = _tool_result_payload(goal_result)

    if not isinstance(payload, dict) or "entries" not in payload:
        reason = _failure_reason(goal_result)
        raise VisionImageReadError(
            f"Could not list directory '{directory}'"
            + (f": {reason}" if reason else ".")
        )

    entries = payload["entries"]

    return [
        str(entry["path"])
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("is_file")
        and (pattern or str(entry.get("name", "")).lower().endswith(IMAGE_SUFFIXES))
    ]


def analyze_with_provider(
    brain: Brain,
    provider_capability_id: str,
    images_base64: tuple[str, ...],
    instruction: str,
    *,
    execution_requirements: object = None,
) -> str:
    """
    Analyze one or more base64-encoded images by constructing a
    Provider-backed nested Goal targeting `provider_capability_id`
    (`CapabilityCategory.VISION`) -- resolved, selected, and executed
    entirely by the existing, unmodified Planner/Model Selection
    Framework/Provider abstraction, exactly like
    `VisionToolDriver._analyze()`. Supports more than one image per
    call (e.g. side-by-side comparison) via the provider-independent
    `ChatMessage.images` tuple (`parika/core/provider_manager
    /chat_message.py`); the selected Provider's driver translates it
    into its own concrete wire field.

    Every deterministic-first Capability in this Module (comparison,
    counting, classification, quality/anomaly narration, ...) only
    ever reaches this function when its own deterministic algorithm
    was inconclusive or the caller explicitly asked for a semantic
    explanation -- see each ToolDriver's own docstring.
    """

    def _build_vision_request(
        resolution: CapabilityResolution,
        model: ProviderModel,
    ) -> ProviderRequest:
        return ChatRequest(
            messages=(
                ChatMessage(
                    role="user", content=instruction, images=images_base64
                ),
            ),
        )

    goal = Goal(
        id=uuid4().hex,
        capability_id=provider_capability_id,
        inputs={"instruction": instruction},
        provider_request_builder=_build_vision_request,
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
        raise VisionAnalysisError(
            "Vision analysis did not succeed"
            + (f": {reason}" if reason else ".")
        )

    backend_response = goal_result.response.outputs.get("result")

    if isinstance(backend_response, ChatResult):
        return backend_response.message.content

    return str(backend_response)


def decode_base64_image(image_base64: str):
    """
    Decode a base64-encoded image into a Pillow `Image`, applying its
    own EXIF orientation tag if any -- exactly like OCR's
    `preprocessing.decode_image()`, operating on an already-base64
    payload (this Module's images always arrive that way, from
    `read_image_base64()`).
    """

    from PIL import Image, ImageOps

    raw_bytes = base64.b64decode(image_base64)
    image = Image.open(io.BytesIO(raw_bytes))
    image.load()
    return ImageOps.exif_transpose(image)


def encode_image_base64(
    image, *, image_format: str = "PNG", quality: int | None = None
) -> str:
    """
    Encode a Pillow `Image` back to a base64 string, for
    `write_image_base64()`. `quality` is forwarded to Pillow's
    `save()` only for lossy formats (e.g. JPEG/WEBP); ignored
    otherwise.
    """

    buffer = io.BytesIO()
    to_save = (
        image.convert("RGB")
        if image_format.upper() in ("JPEG", "JPG")
        else image
    )
    save_kwargs: dict = {"format": image_format}

    if quality is not None:
        save_kwargs["quality"] = quality

    to_save.save(buffer, **save_kwargs)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
