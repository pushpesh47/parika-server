"""
PARIKA Video Module - Driver

Implements the `ModuleDriver` contract for the Video Module, following
exactly the same Capability/Tool registration shape
`OcrModuleDriver`/`VisionModuleDriver`/`DocumentModuleDriver` already
establish (see `module_driver._register_tool()` below, mirroring
`document/module_driver.py`'s own `_register_tool()` helper).

On start(), for each of the thirty `video.*` TOOL Capability/Tool
pairs declared in `_VIDEO_TOOL_SPECS`, registers the Capability
(`CapabilityCategory.TOOL`) and its `tool.video_*` Tool. Six of those
thirty additionally have their own internal, Provider-backed
Capability (`video.provider_describe_video`,
`video.provider_summarize_video`, `video.provider_answer_question`,
`video.provider_classify_video`, `video.provider_detect_key_moments`,
`video.provider_detect_actions`) -- each registered with
`CapabilityCategory.VISION` (this framework has no `VIDEO` category;
reusing `VISION` mirrors OCR's own precedent of reusing `VISION`'s
underlying `ModelCapability.VISION` routing for a different modality
-- see `engine.py`'s own docstring for the full rationale), never a
Tool, and never advertised directly to the general chat model.

Every other `video.*` Capability in this Module reuses a *sibling*
Module's own Provider Capability directly
(`vision.provider_describe_image`, `vision.provider_detect_objects`,
`vision.provider_compare_images`, `ocr.provider_extract_text`) rather
than registering a new one of its own -- see `engine.py`'s docstring
for why that is architecturally sound, and why this Module therefore
registers fewer Provider Capabilities than public Capabilities,
unlike Vision's own 1:1 pairing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from parika.core.brain.brain import Brain
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.health_manager.health_check_result import HealthCheckResult
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.driver import ModuleDriver
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import ProgressReporter

from .config import load_video_config
from .tool_affordances_phase1 import (
    VIDEO_EXTRACT_FRAMES_TOOL_AFFORDANCE,
    VIDEO_EXTRACT_KEYFRAMES_TOOL_AFFORDANCE,
    VIDEO_EXTRACT_METADATA_TOOL_AFFORDANCE,
    VIDEO_EXTRACT_THUMBNAILS_TOOL_AFFORDANCE,
    VIDEO_READ_VIDEO_TOOL_AFFORDANCE,
)
from .tool_affordances_phase2 import (
    VIDEO_ANSWER_QUESTION_TOOL_AFFORDANCE,
    VIDEO_CLASSIFY_VIDEO_TOOL_AFFORDANCE,
    VIDEO_DESCRIBE_VIDEO_TOOL_AFFORDANCE,
    VIDEO_SUMMARIZE_VIDEO_TOOL_AFFORDANCE,
)
from .tool_affordances_phase3 import (
    VIDEO_DETECT_KEY_MOMENTS_TOOL_AFFORDANCE,
    VIDEO_DETECT_SCENE_CHANGES_TOOL_AFFORDANCE,
    VIDEO_DETECT_SHOTS_TOOL_AFFORDANCE,
    VIDEO_GENERATE_TIMELINE_TOOL_AFFORDANCE,
    VIDEO_SEGMENT_VIDEO_TOOL_AFFORDANCE,
)
from .tool_affordances_phase4 import (
    VIDEO_COMPARE_FRAMES_TOOL_AFFORDANCE,
    VIDEO_COUNT_OBJECTS_TOOL_AFFORDANCE,
    VIDEO_DETECT_MOTION_TOOL_AFFORDANCE,
    VIDEO_DETECT_OBJECTS_TOOL_AFFORDANCE,
    VIDEO_TRACK_OBJECTS_TOOL_AFFORDANCE,
)
from .tool_affordances_phase5 import (
    VIDEO_COMPARE_VIDEOS_TOOL_AFFORDANCE,
    VIDEO_DETECT_ACTIONS_TOOL_AFFORDANCE,
    VIDEO_DETECT_BLACK_FRAMES_TOOL_AFFORDANCE,
    VIDEO_DETECT_BLUR_TOOL_AFFORDANCE,
    VIDEO_DETECT_CORRUPTION_TOOL_AFFORDANCE,
    VIDEO_DETECT_DOCUMENTS_TOOL_AFFORDANCE,
    VIDEO_DETECT_EVENTS_TOOL_AFFORDANCE,
    VIDEO_DETECT_ROTATION_TOOL_AFFORDANCE,
    VIDEO_DETECT_SLIDES_TOOL_AFFORDANCE,
    VIDEO_EXTRACT_TABLES_TOOL_AFFORDANCE,
    VIDEO_EXTRACT_TEXT_TOOL_AFFORDANCE,
)
from .tool_driver_factory import build_tool_drivers
from .video_capability_ids import (
    ANSWER_QUESTION_CAPABILITY_ID,
    ANSWER_QUESTION_PROVIDER_CAPABILITY_ID,
    ANSWER_QUESTION_TOOL_ID,
    CLASSIFY_VIDEO_CAPABILITY_ID,
    CLASSIFY_VIDEO_PROVIDER_CAPABILITY_ID,
    CLASSIFY_VIDEO_TOOL_ID,
    COMPARE_FRAMES_CAPABILITY_ID,
    COMPARE_FRAMES_TOOL_ID,
    COMPARE_VIDEOS_CAPABILITY_ID,
    COMPARE_VIDEOS_TOOL_ID,
    COUNT_OBJECTS_CAPABILITY_ID,
    COUNT_OBJECTS_TOOL_ID,
    DESCRIBE_VIDEO_CAPABILITY_ID,
    DESCRIBE_VIDEO_PROVIDER_CAPABILITY_ID,
    DESCRIBE_VIDEO_TOOL_ID,
    DETECT_ACTIONS_CAPABILITY_ID,
    DETECT_ACTIONS_PROVIDER_CAPABILITY_ID,
    DETECT_ACTIONS_TOOL_ID,
    DETECT_BLACK_FRAMES_CAPABILITY_ID,
    DETECT_BLACK_FRAMES_TOOL_ID,
    DETECT_BLUR_CAPABILITY_ID,
    DETECT_BLUR_TOOL_ID,
    DETECT_CORRUPTION_CAPABILITY_ID,
    DETECT_CORRUPTION_TOOL_ID,
    DETECT_DOCUMENTS_CAPABILITY_ID,
    DETECT_DOCUMENTS_TOOL_ID,
    DETECT_EVENTS_CAPABILITY_ID,
    DETECT_EVENTS_TOOL_ID,
    DETECT_KEY_MOMENTS_CAPABILITY_ID,
    DETECT_KEY_MOMENTS_PROVIDER_CAPABILITY_ID,
    DETECT_KEY_MOMENTS_TOOL_ID,
    DETECT_MOTION_CAPABILITY_ID,
    DETECT_MOTION_TOOL_ID,
    DETECT_OBJECTS_CAPABILITY_ID,
    DETECT_OBJECTS_TOOL_ID,
    DETECT_ROTATION_CAPABILITY_ID,
    DETECT_ROTATION_TOOL_ID,
    DETECT_SCENE_CHANGES_CAPABILITY_ID,
    DETECT_SCENE_CHANGES_TOOL_ID,
    DETECT_SHOTS_CAPABILITY_ID,
    DETECT_SHOTS_TOOL_ID,
    DETECT_SLIDES_CAPABILITY_ID,
    DETECT_SLIDES_TOOL_ID,
    EXTRACT_FRAMES_CAPABILITY_ID,
    EXTRACT_FRAMES_TOOL_ID,
    EXTRACT_KEYFRAMES_CAPABILITY_ID,
    EXTRACT_KEYFRAMES_TOOL_ID,
    EXTRACT_METADATA_CAPABILITY_ID,
    EXTRACT_METADATA_TOOL_ID,
    EXTRACT_TABLES_CAPABILITY_ID,
    EXTRACT_TABLES_TOOL_ID,
    EXTRACT_TEXT_CAPABILITY_ID,
    EXTRACT_TEXT_TOOL_ID,
    EXTRACT_THUMBNAILS_CAPABILITY_ID,
    EXTRACT_THUMBNAILS_TOOL_ID,
    GENERATE_TIMELINE_CAPABILITY_ID,
    GENERATE_TIMELINE_TOOL_ID,
    READ_VIDEO_CAPABILITY_ID,
    READ_VIDEO_TOOL_ID,
    SEGMENT_VIDEO_CAPABILITY_ID,
    SEGMENT_VIDEO_TOOL_ID,
    SUMMARIZE_VIDEO_CAPABILITY_ID,
    SUMMARIZE_VIDEO_PROVIDER_CAPABILITY_ID,
    SUMMARIZE_VIDEO_TOOL_ID,
    TRACK_OBJECTS_CAPABILITY_ID,
    TRACK_OBJECTS_TOOL_ID,
)

VIDEO_TOOL_VERSION = "1.0.0"

MODULE_HEALTH_COMPONENT_ID = "module.video"


@dataclass(frozen=True, slots=True, kw_only=True)
class _VideoToolSpec:
    """
    Immutable declaration of one `video.*` TOOL Capability/Tool pair,
    and -- for the six Capabilities that need one -- its own internal
    Provider Capability. Purely data, mirroring
    `document/module_driver.py`'s own per-Capability spec tables.
    """

    tool_capability_id: str
    tool_id: str
    name: str
    tool_description: str
    tool_affordance: Mapping[str, Any]
    provider_capability_id: str | None = None
    provider_description: str | None = None


_VIDEO_TOOL_SPECS: tuple[_VideoToolSpec, ...] = (
    _VideoToolSpec(
        tool_capability_id=READ_VIDEO_CAPABILITY_ID,
        tool_id=READ_VIDEO_TOOL_ID,
        name="Video - Read Video",
        tool_description="Validates a local video file and reports its basic properties.",
        tool_affordance=VIDEO_READ_VIDEO_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=EXTRACT_METADATA_CAPABILITY_ID,
        tool_id=EXTRACT_METADATA_TOOL_ID,
        name="Video - Extract Metadata",
        tool_description="Deterministically extracts a local video's duration/dimensions/frame rate/codec/bitrate/audio presence.",
        tool_affordance=VIDEO_EXTRACT_METADATA_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=EXTRACT_FRAMES_CAPABILITY_ID,
        tool_id=EXTRACT_FRAMES_TOOL_ID,
        name="Video - Extract Frames",
        tool_description="Deterministically extracts frames from a local video via adaptive sampling.",
        tool_affordance=VIDEO_EXTRACT_FRAMES_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=EXTRACT_KEYFRAMES_CAPABILITY_ID,
        tool_id=EXTRACT_KEYFRAMES_TOOL_ID,
        name="Video - Extract Keyframes",
        tool_description="Deterministically extracts one representative frame per detected shot.",
        tool_affordance=VIDEO_EXTRACT_KEYFRAMES_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=EXTRACT_THUMBNAILS_CAPABILITY_ID,
        tool_id=EXTRACT_THUMBNAILS_TOOL_ID,
        name="Video - Extract Thumbnails",
        tool_description="Deterministically generates a contact-sheet thumbnail image for a local video.",
        tool_affordance=VIDEO_EXTRACT_THUMBNAILS_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DESCRIBE_VIDEO_CAPABILITY_ID,
        tool_id=DESCRIBE_VIDEO_TOOL_ID,
        name="Video - Describe Video",
        tool_description="Samples representative frames and describes a local video via a video-capable Provider model.",
        tool_affordance=VIDEO_DESCRIBE_VIDEO_TOOL_AFFORDANCE,
        provider_capability_id=DESCRIBE_VIDEO_PROVIDER_CAPABILITY_ID,
        provider_description="AI-driven video description, satisfied by a Provider model specialized for vision/video understanding (e.g. `minicpm-v4.5`).",
    ),
    _VideoToolSpec(
        tool_capability_id=SUMMARIZE_VIDEO_CAPABILITY_ID,
        tool_id=SUMMARIZE_VIDEO_TOOL_ID,
        name="Video - Summarize Video",
        tool_description="Samples representative frames and summarizes a local video's key events via a video-capable Provider model.",
        tool_affordance=VIDEO_SUMMARIZE_VIDEO_TOOL_AFFORDANCE,
        provider_capability_id=SUMMARIZE_VIDEO_PROVIDER_CAPABILITY_ID,
        provider_description="AI-driven video summarization, satisfied by a Provider model specialized for vision/video understanding.",
    ),
    _VideoToolSpec(
        tool_capability_id=ANSWER_QUESTION_CAPABILITY_ID,
        tool_id=ANSWER_QUESTION_TOOL_ID,
        name="Video - Answer Question",
        tool_description="Samples representative (optionally timestamp-focused) frames and answers a specific question about a local video.",
        tool_affordance=VIDEO_ANSWER_QUESTION_TOOL_AFFORDANCE,
        provider_capability_id=ANSWER_QUESTION_PROVIDER_CAPABILITY_ID,
        provider_description="AI-driven video question answering, satisfied by a Provider model specialized for vision/video understanding.",
    ),
    _VideoToolSpec(
        tool_capability_id=CLASSIFY_VIDEO_CAPABILITY_ID,
        tool_id=CLASSIFY_VIDEO_TOOL_ID,
        name="Video - Classify Video",
        tool_description="Deterministically classifies a local video's activity level; escalates to a Provider model only for open-set candidate labels.",
        tool_affordance=VIDEO_CLASSIFY_VIDEO_TOOL_AFFORDANCE,
        provider_capability_id=CLASSIFY_VIDEO_PROVIDER_CAPABILITY_ID,
        provider_description="AI-driven open-set video classification, satisfied by a Provider model specialized for vision/video understanding. Only consulted when candidate_labels are supplied.",
    ),
    _VideoToolSpec(
        tool_capability_id=GENERATE_TIMELINE_CAPABILITY_ID,
        tool_id=GENERATE_TIMELINE_TOOL_ID,
        name="Video - Generate Timeline",
        tool_description="Builds a structured, timestamped timeline of a local video's key moments.",
        tool_affordance=VIDEO_GENERATE_TIMELINE_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_SCENE_CHANGES_CAPABILITY_ID,
        tool_id=DETECT_SCENE_CHANGES_TOOL_ID,
        name="Video - Detect Scene Changes",
        tool_description="Deterministically detects abrupt visual scene changes in a local video.",
        tool_affordance=VIDEO_DETECT_SCENE_CHANGES_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_SHOTS_CAPABILITY_ID,
        tool_id=DETECT_SHOTS_TOOL_ID,
        name="Video - Detect Shots",
        tool_description="Deterministically detects shot (cut) boundaries in a local video at fine temporal granularity.",
        tool_affordance=VIDEO_DETECT_SHOTS_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=SEGMENT_VIDEO_CAPABILITY_ID,
        tool_id=SEGMENT_VIDEO_TOOL_ID,
        name="Video - Segment Video",
        tool_description="Deterministically splits a local video into contiguous temporal segments at detected shot boundaries.",
        tool_affordance=VIDEO_SEGMENT_VIDEO_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_KEY_MOMENTS_CAPABILITY_ID,
        tool_id=DETECT_KEY_MOMENTS_TOOL_ID,
        name="Video - Detect Key Moments",
        tool_description="Deterministically ranks a local video's most visually significant moments; optionally explained by a Provider model.",
        tool_affordance=VIDEO_DETECT_KEY_MOMENTS_TOOL_AFFORDANCE,
        provider_capability_id=DETECT_KEY_MOMENTS_PROVIDER_CAPABILITY_ID,
        provider_description="AI-driven explanation of deterministically-ranked key moments, satisfied by a Provider model specialized for vision/video understanding. Only consulted when include_explanation is set.",
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_OBJECTS_CAPABILITY_ID,
        tool_id=DETECT_OBJECTS_TOOL_ID,
        name="Video - Detect Objects",
        tool_description="Detects objects across sampled frames of a local video, reusing Vision's own object-detection Capability, with timestamps.",
        tool_affordance=VIDEO_DETECT_OBJECTS_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=COUNT_OBJECTS_CAPABILITY_ID,
        tool_id=COUNT_OBJECTS_TOOL_ID,
        name="Video - Count Objects",
        tool_description="Deterministically counts moving regions per frame in a local video; optionally counts a named object via a Vision model.",
        tool_affordance=VIDEO_COUNT_OBJECTS_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=TRACK_OBJECTS_CAPABILITY_ID,
        tool_id=TRACK_OBJECTS_TOOL_ID,
        name="Video - Track Objects",
        tool_description="Attempts to track objects across a local video's frames; falls back to frame-level detection when no robust tracker is available.",
        tool_affordance=VIDEO_TRACK_OBJECTS_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_MOTION_CAPABILITY_ID,
        tool_id=DETECT_MOTION_TOOL_ID,
        name="Video - Detect Motion",
        tool_description="Deterministically detects meaningful motion between consecutive sampled frames of a local video.",
        tool_affordance=VIDEO_DETECT_MOTION_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=COMPARE_FRAMES_CAPABILITY_ID,
        tool_id=COMPARE_FRAMES_TOOL_ID,
        name="Video - Compare Frames",
        tool_description="Deterministically compares two specific frames (same or different videos) for visual/structural similarity and changed regions.",
        tool_affordance=VIDEO_COMPARE_FRAMES_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_EVENTS_CAPABILITY_ID,
        tool_id=DETECT_EVENTS_TOOL_ID,
        name="Video - Detect Events",
        tool_description="Deterministically detects candidate events over time in a local video: scene changes, motion spikes, black-frame transitions.",
        tool_affordance=VIDEO_DETECT_EVENTS_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_ACTIONS_CAPABILITY_ID,
        tool_id=DETECT_ACTIONS_TOOL_ID,
        name="Video - Detect Actions",
        tool_description="Recognizes actions/activities across sampled frames of a local video via a video-capable Provider model, with a confidence estimate.",
        tool_affordance=VIDEO_DETECT_ACTIONS_TOOL_AFFORDANCE,
        provider_capability_id=DETECT_ACTIONS_PROVIDER_CAPABILITY_ID,
        provider_description="AI-driven action/activity recognition, satisfied by a Provider model specialized for vision/video understanding.",
    ),
    _VideoToolSpec(
        tool_capability_id=EXTRACT_TEXT_CAPABILITY_ID,
        tool_id=EXTRACT_TEXT_TOOL_ID,
        name="Video - Extract Text",
        tool_description="Extracts visible on-screen text from a local video's frames over time, reusing OCR's own text-extraction Capability, deduplicated.",
        tool_affordance=VIDEO_EXTRACT_TEXT_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_DOCUMENTS_CAPABILITY_ID,
        tool_id=DETECT_DOCUMENTS_TOOL_ID,
        name="Video - Detect Documents",
        tool_description="Flags local video frames that appear to contain substantial document-like text.",
        tool_affordance=VIDEO_DETECT_DOCUMENTS_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_SLIDES_CAPABILITY_ID,
        tool_id=DETECT_SLIDES_TOOL_ID,
        name="Video - Detect Slides",
        tool_description="Deterministically detects presentation/slideshow segments (near-static, visually-similar frame spans) in a local video.",
        tool_affordance=VIDEO_DETECT_SLIDES_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=EXTRACT_TABLES_CAPABILITY_ID,
        tool_id=EXTRACT_TABLES_TOOL_ID,
        name="Video - Extract Tables",
        tool_description="Identifies candidate local video frames likely containing a visible table and extracts their raw OCR text.",
        tool_affordance=VIDEO_EXTRACT_TABLES_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=COMPARE_VIDEOS_CAPABILITY_ID,
        tool_id=COMPARE_VIDEOS_TOOL_ID,
        name="Video - Compare Videos",
        tool_description="Compares two local videos: duration, resolution, frame rate, sampled-frame visual similarity, and scene-structure counts; optional semantic difference.",
        tool_affordance=VIDEO_COMPARE_VIDEOS_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_BLUR_CAPABILITY_ID,
        tool_id=DETECT_BLUR_TOOL_ID,
        name="Video - Detect Blur",
        tool_description="Deterministically measures sharpness across a local video's sampled frames.",
        tool_affordance=VIDEO_DETECT_BLUR_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_BLACK_FRAMES_CAPABILITY_ID,
        tool_id=DETECT_BLACK_FRAMES_TOOL_ID,
        name="Video - Detect Black Frames",
        tool_description="Deterministically detects black/near-black frames in a local video.",
        tool_affordance=VIDEO_DETECT_BLACK_FRAMES_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_ROTATION_CAPABILITY_ID,
        tool_id=DETECT_ROTATION_TOOL_ID,
        name="Video - Detect Rotation",
        tool_description="Deterministically estimates whether a local video's frames are unexpectedly rotated.",
        tool_affordance=VIDEO_DETECT_ROTATION_TOOL_AFFORDANCE,
    ),
    _VideoToolSpec(
        tool_capability_id=DETECT_CORRUPTION_CAPABILITY_ID,
        tool_id=DETECT_CORRUPTION_TOOL_ID,
        name="Video - Detect Corruption",
        tool_description="Deterministically checks whether a local video's container or a probe set of frames are unreadable/corrupt.",
        tool_affordance=VIDEO_DETECT_CORRUPTION_TOOL_AFFORDANCE,
    ),
)
"""Every `video.*` TOOL Capability/Tool pair (plus its optional Provider Capability) this Module registers."""


class VideoModuleDriver(ModuleDriver):
    """Runtime driver for the Video Module."""

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        brain: Brain,
        logger: Logger,
        event_bus: EventBus | None = None,
        health_manager: HealthManager | None = None,
        configuration: Configuration | None = None,
    ) -> None:
        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)

        video_config = load_video_config(configuration)
        self._enabled = video_config.enabled

        def _progress_for(capability_id: str) -> ProgressReporter | None:
            return ProgressReporter(event_bus, capability_id) if event_bus is not None else None

        self._tool_drivers = build_tool_drivers(
            brain=brain,
            tool_manager=tool_manager,
            config=video_config,
            progress_for=_progress_for,
        )

    def start(self) -> None:
        if not self._enabled:
            self._logger.info(
                "Video module is disabled by configuration; not registering "
                "its Capabilities or Tools."
            )
            return

        for spec in _VIDEO_TOOL_SPECS:
            self._register_tool(spec)

        if self._health_manager is not None:
            self._health_manager.register(MODULE_HEALTH_COMPONENT_ID, check=self._check_health)

        self._logger.info("Video module started.")

    def stop(self) -> None:
        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        for spec in _VIDEO_TOOL_SPECS:
            self._tool_manager.unregister(spec.tool_id)
            self._capability_registry.unregister(spec.tool_capability_id)

            if spec.provider_capability_id is not None:
                self._capability_registry.unregister(spec.provider_capability_id)

        self._logger.info("Video module stopped.")

    def _register_tool(self, spec: _VideoToolSpec) -> None:
        self._capability_registry.register(
            CapabilityDefinition(
                id=spec.tool_capability_id,
                name=spec.name,
                description=spec.tool_description,
                # TOOL, not VISION: Planner routes a Goal to ToolManager
                # only when `category is CapabilityCategory.TOOL`, and
                # Automatic Capability Discovery only ever advertises
                # TOOL-category Capabilities to the model -- exactly
                # like every other Module in this codebase.
                category=CapabilityCategory.TOOL,
                tags=frozenset({"video"}),
                metadata={"tool_affordance": spec.tool_affordance},  # type: ignore[arg-type]
            )
        )
        self._tool_manager.register(
            Tool(
                id=spec.tool_id,
                name=spec.name,
                version=VIDEO_TOOL_VERSION,
                description=spec.tool_description,
                capabilities=(spec.tool_capability_id,),
            ),
            self._tool_drivers[spec.tool_capability_id],
        )

        if spec.provider_capability_id is not None:
            self._capability_registry.register(
                CapabilityDefinition(
                    id=spec.provider_capability_id,
                    name=f"{spec.name} (Provider)",
                    description=spec.provider_description or "",
                    # VISION, not a new VIDEO category: see this
                    # module's own docstring and `engine.py`'s for why
                    # reusing VISION's existing routing
                    # (`ModelCapability.VISION`) is the correct,
                    # minimal-risk choice for a Provider Capability
                    # that -- like every `vision.provider_*`
                    # Capability -- is satisfied by sending images
                    # (sampled frames) through the provider-independent
                    # ChatMessage.images tuple.
                    category=CapabilityCategory.VISION,
                    tags=frozenset({"video"}),
                )
            )

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)
