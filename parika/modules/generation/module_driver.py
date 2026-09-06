"""
PARIKA Generation Module - Driver

Implements the `ModuleDriver` contract for the Generation Module,
following exactly the same two-Capability-per-Tool shape
`VisionModuleDriver`/`VideoModuleDriver` already establish:

On start(), for each of the five `image.*`/`video.*` Tool specs
declared in `_GENERATION_TOOL_SPECS` below, registers:

- Its advertised TOOL Capability (e.g. `image.generate`,
  `CapabilityCategory.TOOL`) with its own `tool.image_*`/
  `tool.video_*` Tool -- advertised to the general chat model through
  Automatic Capability Discovery/its own Tool Affordance Contract.
- Its internal, Provider-backed Capability (e.g.
  `image.provider_generate`, `CapabilityCategory.IMAGE_GENERATION` or
  `VIDEO_GENERATION`) -- satisfied by a compatible generation Provider
  model (ComfyUI today), never a Tool, and never advertised directly
  to the general chat model.

On stop(), unregisters all ten.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from parika.core.brain.brain import Brain
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
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

from . import capability_ids as ids
from . import tool_affordances as affordances
from .config import load_generation_config
from .driver_image import ImageEditToolDriver, ImageGenerateToolDriver
from .driver_video import (
    VideoEditToolDriver,
    VideoGenerateFromImageToolDriver,
    VideoGenerateToolDriver,
)

GENERATION_TOOL_VERSION = "1.0.0"
MODULE_HEALTH_COMPONENT_ID = "module.generation"


@dataclass(frozen=True, slots=True, kw_only=True)
class GenerationToolSpec:
    """
    Immutable declaration of one `image.*`/`video.*` TOOL Capability/
    Tool pair and the internal, Provider-backed Capability it
    orchestrates.
    """

    tool_capability_id: str
    provider_capability_id: str
    tool_id: str
    name: str
    tool_description: str
    provider_description: str
    provider_category: CapabilityCategory
    tool_affordance: Mapping[str, Any]


_GENERATION_TOOL_SPECS: tuple[GenerationToolSpec, ...] = (
    GenerationToolSpec(
        tool_capability_id=ids.IMAGE_GENERATE_CAPABILITY_ID,
        provider_capability_id=ids.IMAGE_GENERATE_PROVIDER_CAPABILITY_ID,
        tool_id=ids.IMAGE_GENERATE_TOOL_ID,
        name="Image - Generate",
        tool_description=(
            "Orchestrates a Provider-backed image-generation model "
            "to create a new image from a text description."
        ),
        provider_description=(
            "AI-driven image generation, satisfied by a Provider "
            "model specialized for image generation (e.g. ComfyUI's "
            "Qwen-Image)."
        ),
        provider_category=CapabilityCategory.IMAGE_GENERATION,
        tool_affordance=affordances.IMAGE_GENERATE_TOOL_AFFORDANCE,
    ),
    GenerationToolSpec(
        tool_capability_id=ids.IMAGE_EDIT_CAPABILITY_ID,
        provider_capability_id=ids.IMAGE_EDIT_PROVIDER_CAPABILITY_ID,
        tool_id=ids.IMAGE_EDIT_TOOL_ID,
        name="Image - Edit",
        tool_description=(
            "Orchestrates the Filesystem Capability and a Provider-"
            "backed image-generation model to edit an existing local "
            "image according to a text instruction."
        ),
        provider_description=(
            "AI-driven image editing, satisfied by a Provider model "
            "specialized for image generation (e.g. ComfyUI's "
            "Qwen-Image)."
        ),
        provider_category=CapabilityCategory.IMAGE_GENERATION,
        tool_affordance=affordances.IMAGE_EDIT_TOOL_AFFORDANCE,
    ),
    GenerationToolSpec(
        tool_capability_id=ids.VIDEO_GENERATE_CAPABILITY_ID,
        provider_capability_id=ids.VIDEO_GENERATE_PROVIDER_CAPABILITY_ID,
        tool_id=ids.VIDEO_GENERATE_TOOL_ID,
        name="Video - Generate",
        tool_description=(
            "Orchestrates a Provider-backed video-generation model to "
            "create a new video from a text description."
        ),
        provider_description=(
            "AI-driven text-to-video generation, satisfied by a "
            "Provider model specialized for video generation (e.g. "
            "ComfyUI's Wan2.1)."
        ),
        provider_category=CapabilityCategory.VIDEO_GENERATION,
        tool_affordance=affordances.VIDEO_GENERATE_TOOL_AFFORDANCE,
    ),
    GenerationToolSpec(
        tool_capability_id=ids.VIDEO_GENERATE_FROM_IMAGE_CAPABILITY_ID,
        provider_capability_id=(
            ids.VIDEO_GENERATE_FROM_IMAGE_PROVIDER_CAPABILITY_ID
        ),
        tool_id=ids.VIDEO_GENERATE_FROM_IMAGE_TOOL_ID,
        name="Video - Generate From Image",
        tool_description=(
            "Orchestrates the Filesystem Capability and a Provider-"
            "backed video-generation model to animate an existing "
            "local image into a new video."
        ),
        provider_description=(
            "AI-driven image-to-video generation, satisfied by a "
            "Provider model specialized for video generation with "
            "image conditioning (e.g. ComfyUI's Wan2.1 VACE)."
        ),
        provider_category=CapabilityCategory.VIDEO_GENERATION,
        tool_affordance=affordances.VIDEO_GENERATE_FROM_IMAGE_TOOL_AFFORDANCE,
    ),
    GenerationToolSpec(
        tool_capability_id=ids.VIDEO_EDIT_CAPABILITY_ID,
        provider_capability_id=ids.VIDEO_EDIT_PROVIDER_CAPABILITY_ID,
        tool_id=ids.VIDEO_EDIT_TOOL_ID,
        name="Video - Edit",
        tool_description=(
            "Orchestrates the Filesystem Capability and a Provider-"
            "backed video-generation model to transform an existing "
            "local video according to a text instruction."
        ),
        provider_description=(
            "AI-driven video-to-video editing, satisfied by a "
            "Provider model specialized for video generation with "
            "video conditioning (e.g. ComfyUI's Wan2.1 VACE)."
        ),
        provider_category=CapabilityCategory.VIDEO_GENERATION,
        tool_affordance=affordances.VIDEO_EDIT_TOOL_AFFORDANCE,
    ),
)


class GenerationModuleDriver(ModuleDriver):
    """
    Runtime driver for the Generation Module.
    """

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

        generation_config = load_generation_config(configuration)
        self._enabled = generation_config.enabled

        def _progress_for(capability_id: str) -> ProgressReporter | None:
            return (
                ProgressReporter(event_bus, capability_id)
                if event_bus is not None
                else None
            )

        self._tool_drivers: dict[str, Any] = {
            ids.IMAGE_GENERATE_CAPABILITY_ID: ImageGenerateToolDriver(
                brain=brain,
                provider_capability_id=ids.IMAGE_GENERATE_PROVIDER_CAPABILITY_ID,
                config=generation_config,
                progress_reporter=_progress_for(ids.IMAGE_GENERATE_CAPABILITY_ID),
            ),
            ids.IMAGE_EDIT_CAPABILITY_ID: ImageEditToolDriver(
                brain=brain,
                provider_capability_id=ids.IMAGE_EDIT_PROVIDER_CAPABILITY_ID,
                config=generation_config,
                progress_reporter=_progress_for(ids.IMAGE_EDIT_CAPABILITY_ID),
            ),
            ids.VIDEO_GENERATE_CAPABILITY_ID: VideoGenerateToolDriver(
                brain=brain,
                provider_capability_id=ids.VIDEO_GENERATE_PROVIDER_CAPABILITY_ID,
                config=generation_config,
                progress_reporter=_progress_for(ids.VIDEO_GENERATE_CAPABILITY_ID),
            ),
            ids.VIDEO_GENERATE_FROM_IMAGE_CAPABILITY_ID: (
                VideoGenerateFromImageToolDriver(
                    brain=brain,
                    provider_capability_id=(
                        ids.VIDEO_GENERATE_FROM_IMAGE_PROVIDER_CAPABILITY_ID
                    ),
                    config=generation_config,
                    progress_reporter=_progress_for(
                        ids.VIDEO_GENERATE_FROM_IMAGE_CAPABILITY_ID
                    ),
                )
            ),
            ids.VIDEO_EDIT_CAPABILITY_ID: VideoEditToolDriver(
                brain=brain,
                provider_capability_id=ids.VIDEO_EDIT_PROVIDER_CAPABILITY_ID,
                config=generation_config,
                progress_reporter=_progress_for(ids.VIDEO_EDIT_CAPABILITY_ID),
            ),
        }

    def start(self) -> None:
        if not self._enabled:
            self._logger.info(
                "Generation module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        for spec in _GENERATION_TOOL_SPECS:
            self._capability_registry.register(
                CapabilityDefinition(
                    id=spec.tool_capability_id,
                    name=spec.name,
                    description=spec.tool_description,
                    # TOOL, not IMAGE_GENERATION/VIDEO_GENERATION:
                    # Planner routes a Goal to ToolManager only when
                    # `category is CapabilityCategory.TOOL` (every
                    # other category is assumed to require a Provider
                    # model) -- and Automatic Capability Discovery
                    # only ever advertises TOOL-category Capabilities
                    # to the model. This Capability is backed by a
                    # real, deterministic-dispatch ToolDriver, so it
                    # must be TOOL for either to work, exactly like
                    # `vision.remove_background`.
                    category=CapabilityCategory.TOOL,
                    tags=frozenset({"generation", "media"}),
                    metadata={  # type: ignore[arg-type]
                        "tool_affordance": spec.tool_affordance,
                        "decomposition_terminal": True,
                    },
                )
            )
            self._tool_manager.register(
                Tool(
                    id=spec.tool_id,
                    name=spec.name,
                    version=GENERATION_TOOL_VERSION,
                    description=spec.tool_description,
                    capabilities=(spec.tool_capability_id,),
                ),
                self._tool_drivers[spec.tool_capability_id],
            )

            self._capability_registry.register(
                CapabilityDefinition(
                    id=spec.provider_capability_id,
                    name=f"{spec.name} (Provider)",
                    description=spec.provider_description,
                    # IMAGE_GENERATION/VIDEO_GENERATION, Provider-
                    # routed -- never a Tool, and never advertised to
                    # the general chat model.
                    category=spec.provider_category,
                    tags=frozenset({"generation"}),
                )
            )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("Generation module started.")

    def stop(self) -> None:
        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        for spec in _GENERATION_TOOL_SPECS:
            self._tool_manager.unregister(spec.tool_id)
            self._capability_registry.unregister(spec.tool_capability_id)
            self._capability_registry.unregister(spec.provider_capability_id)

        self._logger.info("Generation module stopped.")

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)
