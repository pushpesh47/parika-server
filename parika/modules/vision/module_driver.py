"""
PARIKA Vision Module - Driver

Implements the `ModuleDriver` contract for the Vision Module, following
exactly the same two-Capability-per-Tool shape `OcrModuleDriver`
already establishes for the OCR Module
(`parika/modules/ocr/module_driver.py`), itself mirroring
`CodingAgentModuleDriver` (`parika/modules/coding_agent/module_driver.py`):

On start(), for each of the seven `vision.*` Tool specs declared in
`_VISION_TOOL_SPECS` below, registers:

- Its advertised TOOL Capability (e.g. `vision.describe_image`,
  `CapabilityCategory.TOOL`) with its own `tool.vision_*` Tool --
  advertised to the general chat model through Automatic Capability
  Discovery/its own Tool Affordance Contract, exactly like
  `ocr.extract_text`.
- Its internal, Provider-backed Capability (e.g.
  `vision.provider_describe_image`, `CapabilityCategory.VISION`) --
  satisfied by a Vision-capable Provider model (e.g. `minicpm-v4.5`),
  never a Tool, and never advertised directly to the general chat
  model (Automatic Capability Discovery only ever discovers
  TOOL-category Capabilities -- see
  `parika/interfaces/ai_context/capability_context.py`), exactly like
  `ocr.provider_extract_text`.

On stop(), unregisters all fourteen.

This is a single Module registering seven Tool/Provider Capability
pairs instead of one, purely because every pair shares the exact same
two-step orchestration shape (`VisionToolDriver`, see `driver.py`) and
the exact same underlying Model Selection routing
(`CapabilityCategory.VISION -> ModelCapability.VISION ->
TaskCategory.VISION_UNDERSTANDING`) -- it introduces no new execution
architecture beyond what OCR already established.
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

from .config import load_vision_config
from .driver import VisionToolDriver
from .extended_tool_drivers import build_extended_tool_drivers
from .extended_tool_specs import _VISION_EXTENDED_TOOL_SPECS

VISION_TOOL_VERSION = "1.0.0"

MODULE_HEALTH_COMPONENT_ID = "module.vision"


@dataclass(frozen=True, slots=True, kw_only=True)
class VisionToolSpec:
    """
    Immutable declaration of one `vision.*` TOOL Capability/Tool pair
    and the internal, Provider-backed Capability it orchestrates.

    Purely data -- adding a new Vision Capability (e.g. a future
    `vision.analyze_document_layout`) means adding one more entry to
    `_VISION_TOOL_SPECS`, not writing a new driver class.
    """

    tool_capability_id: str
    """Advertised `CapabilityCategory.TOOL` id (e.g. `"vision.describe_image"`)."""

    provider_capability_id: str
    """Internal `CapabilityCategory.VISION` id (e.g. `"vision.provider_describe_image"`)."""

    tool_id: str
    """`Tool.id` (e.g. `"tool.vision_describe_image"`)."""

    name: str
    """Human-readable `Tool.name`/`CapabilityDefinition.name` suffix."""

    tool_description: str
    """`CapabilityDefinition.description` for the TOOL Capability."""

    provider_description: str
    """`CapabilityDefinition.description` for the Provider Capability."""

    default_instruction: str
    """Default instruction sent to the Vision model. Ignored when
    `question_argument=True`."""

    question_argument: bool
    """Whether this Tool requires a `question` argument instead of an
    optional `instruction` one (only `vision.answer_question`)."""

    tool_affordance: Mapping[str, Any]
    """This Capability's Tool Affordance Contract (see
    `parika/interfaces/ai_context/tool_context.py`)."""


_PATH_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the image.",
}

_INSTRUCTION_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": (
        "What to focus on. Optional; defaults to a general analysis "
        "for this capability."
    ),
}

_VISION_TOOL_SPECS: tuple[VisionToolSpec, ...] = (
    VisionToolSpec(
        tool_capability_id="vision.describe_image",
        provider_capability_id="vision.provider_describe_image",
        tool_id="tool.vision_describe_image",
        name="Vision - Describe Image",
        tool_description=(
            "Orchestrates the Filesystem Capability and a "
            "Provider-backed Vision model to describe a local image "
            "file in detail."
        ),
        provider_description=(
            "AI-driven general image description, satisfied by a "
            "Provider model specialized for vision understanding "
            "(e.g. `minicpm-v4.5`)."
        ),
        default_instruction=(
            "Describe this image in detail: what it shows, notable "
            "subjects, and overall context."
        ),
        question_argument=False,
        tool_affordance={
            "purpose": (
                "Provides a general natural-language description of "
                "an image file already stored locally."
            ),
            "use_when": (
                "the user wants a general description or summary of "
                "an image (e.g. \"describe this image\", "
                "\"summarize this photograph\", \"explain what you "
                "see\")."
            ),
            "avoid_when": (
                "the user asks a specific question about the image "
                "(use `vision_answer_question`), wants objects "
                "counted/found (use `vision_detect_objects`), or "
                "wants text extracted (use OCR's `ocr_extract_text`)."
            ),
            "requires": "the image file path; ask the user for it if not already known.",
            "result_semantics": (
                "Returns the description. Present it directly, in "
                "prose, rather than as raw tool output."
            ),
            "failure_semantics": (
                "If the image cannot be read or no Vision-capable "
                "model is currently available, explain the problem "
                "in plain language without exposing internal "
                "exception details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": _PATH_PARAMETER,
                    "instruction": _INSTRUCTION_PARAMETER,
                },
                "required": ["path"],
            },
        },
    ),
    VisionToolSpec(
        tool_capability_id="vision.answer_question",
        provider_capability_id="vision.provider_answer_question",
        tool_id="tool.vision_answer_question",
        name="Vision - Answer Question",
        tool_description=(
            "Orchestrates the Filesystem Capability and a "
            "Provider-backed Vision model to answer a specific "
            "question about a local image file (Visual Question "
            "Answering)."
        ),
        provider_description=(
            "AI-driven Visual Question Answering, satisfied by a "
            "Provider model specialized for vision understanding "
            "(e.g. `minicpm-v4.5`)."
        ),
        default_instruction="",
        question_argument=True,
        tool_affordance={
            "purpose": (
                "Answers a specific question about an image file "
                "already stored locally (Visual Question Answering)."
            ),
            "use_when": (
                "the user asks a specific question about an image "
                "(e.g. \"what is the man holding?\", \"what color is "
                "the car?\", \"how many chairs are visible?\")."
            ),
            "avoid_when": (
                "the user wants a general description instead (use "
                "`vision_describe_image`), or wants text extracted "
                "(use OCR's `ocr_extract_text`)."
            ),
            "requires": (
                "the image file path and the specific question to "
                "answer; ask the user for either if not already "
                "known."
            ),
            "result_semantics": (
                "Returns the answer. Present it directly, answering "
                "the user's question in plain language."
            ),
            "failure_semantics": (
                "If the image cannot be read or no Vision-capable "
                "model is currently available, explain the problem "
                "in plain language without exposing internal "
                "exception details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": _PATH_PARAMETER,
                    "question": {
                        "type": "string",
                        "description": (
                            "The specific question to answer about "
                            "the image."
                        ),
                    },
                },
                "required": ["path", "question"],
            },
        },
    ),
    VisionToolSpec(
        tool_capability_id="vision.detect_objects",
        provider_capability_id="vision.provider_detect_objects",
        tool_id="tool.vision_detect_objects",
        name="Vision - Detect Objects",
        tool_description=(
            "Orchestrates the Filesystem Capability and a "
            "Provider-backed Vision model to detect, count, or find "
            "objects within a local image file."
        ),
        provider_description=(
            "AI-driven object detection/counting, satisfied by a "
            "Provider model specialized for vision understanding "
            "(e.g. `minicpm-v4.5`)."
        ),
        default_instruction=(
            "Detect and list every distinct object visible in this "
            "image, with an approximate count for each."
        ),
        question_argument=False,
        tool_affordance={
            "purpose": (
                "Detects, counts, or locates objects within an image "
                "file already stored locally."
            ),
            "use_when": (
                "the user wants objects found or counted (e.g. "
                "\"count people\", \"find all laptops\", \"detect "
                "traffic signs\")."
            ),
            "avoid_when": (
                "the user wants a general description instead (use "
                "`vision_describe_image`)."
            ),
            "requires": (
                "the image file path; ask the user for it if not "
                "already known. Optionally, which object(s) to focus "
                "on."
            ),
            "result_semantics": (
                "Returns the detected objects and, where relevant, "
                "their counts. Present them directly, formatted the "
                "way the user asked for it."
            ),
            "failure_semantics": (
                "If the image cannot be read or no Vision-capable "
                "model is currently available, explain the problem "
                "in plain language without exposing internal "
                "exception details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": _PATH_PARAMETER,
                    "instruction": {
                        "type": "string",
                        "description": (
                            "Which object(s) to detect or count. "
                            "Optional; defaults to detecting every "
                            "visible object."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    ),
    VisionToolSpec(
        tool_capability_id="vision.analyze_scene",
        provider_capability_id="vision.provider_analyze_scene",
        tool_id="tool.vision_analyze_scene",
        name="Vision - Analyze Scene",
        tool_description=(
            "Orchestrates the Filesystem Capability and a "
            "Provider-backed Vision model to analyze a local image "
            "file's scene/environment."
        ),
        provider_description=(
            "AI-driven scene analysis, satisfied by a Provider model "
            "specialized for vision understanding (e.g. "
            "`minicpm-v4.5`)."
        ),
        default_instruction=(
            "Describe the scene: setting, environment (indoor or "
            "outdoor), and overall context."
        ),
        question_argument=False,
        tool_affordance={
            "purpose": (
                "Analyzes an image's scene or environment (setting, "
                "indoor/outdoor, overall context)."
            ),
            "use_when": (
                "the user wants the environment or scene described "
                "(e.g. \"describe the environment\", \"indoor or "
                "outdoor?\", \"explain the scene\")."
            ),
            "avoid_when": (
                "the user wants a general subject-focused description "
                "instead (use `vision_describe_image`)."
            ),
            "requires": "the image file path; ask the user for it if not already known.",
            "result_semantics": (
                "Returns the scene analysis. Present it directly, in "
                "prose."
            ),
            "failure_semantics": (
                "If the image cannot be read or no Vision-capable "
                "model is currently available, explain the problem "
                "in plain language without exposing internal "
                "exception details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": _PATH_PARAMETER,
                    "instruction": _INSTRUCTION_PARAMETER,
                },
                "required": ["path"],
            },
        },
    ),
    VisionToolSpec(
        tool_capability_id="vision.analyze_ui",
        provider_capability_id="vision.provider_analyze_ui",
        tool_id="tool.vision_analyze_ui",
        name="Vision - Analyze UI",
        tool_description=(
            "Orchestrates the Filesystem Capability and a "
            "Provider-backed Vision model to analyze a local "
            "application UI or webpage screenshot."
        ),
        provider_description=(
            "AI-driven UI/screenshot analysis, satisfied by a "
            "Provider model specialized for vision understanding "
            "(e.g. `minicpm-v4.5`)."
        ),
        default_instruction=(
            "Explain this user interface or webpage screenshot: "
            "layout, visible elements, and their apparent purpose."
        ),
        question_argument=False,
        tool_affordance={
            "purpose": (
                "Analyzes an application UI or webpage screenshot "
                "already stored locally."
            ),
            "use_when": (
                "the user wants a UI, webpage, or screenshot "
                "reviewed or explained (e.g. \"explain this "
                "application UI\", \"describe this webpage\", "
                "\"review this screenshot\")."
            ),
            "avoid_when": (
                "the image is not a UI/screenshot (use "
                "`vision_describe_image` instead)."
            ),
            "requires": "the image file path; ask the user for it if not already known.",
            "result_semantics": (
                "Returns the UI analysis. Present it directly, in "
                "prose, describing the layout and elements."
            ),
            "failure_semantics": (
                "If the image cannot be read or no Vision-capable "
                "model is currently available, explain the problem "
                "in plain language without exposing internal "
                "exception details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": _PATH_PARAMETER,
                    "instruction": _INSTRUCTION_PARAMETER,
                },
                "required": ["path"],
            },
        },
    ),
    VisionToolSpec(
        tool_capability_id="vision.analyze_chart",
        provider_capability_id="vision.provider_analyze_chart",
        tool_id="tool.vision_analyze_chart",
        name="Vision - Analyze Chart",
        tool_description=(
            "Orchestrates the Filesystem Capability and a "
            "Provider-backed Vision model to analyze a local chart, "
            "graph, or plot image."
        ),
        provider_description=(
            "AI-driven chart/graph analysis, satisfied by a Provider "
            "model specialized for vision understanding (e.g. "
            "`minicpm-v4.5`)."
        ),
        default_instruction=(
            "Explain this chart or graph: its type, axes/labels, and "
            "the key trends or values it shows."
        ),
        question_argument=False,
        tool_affordance={
            "purpose": (
                "Analyzes a chart, graph, or plot image already "
                "stored locally."
            ),
            "use_when": (
                "the user wants a chart, graph, or plot explained "
                "(e.g. \"explain this graph\", \"summarize this "
                "chart\", \"interpret the plot\")."
            ),
            "avoid_when": (
                "the image is not a chart/graph (use "
                "`vision_describe_image` instead)."
            ),
            "requires": "the image file path; ask the user for it if not already known.",
            "result_semantics": (
                "Returns the chart analysis. Present it directly, in "
                "prose, referencing the specific trends/values found."
            ),
            "failure_semantics": (
                "If the image cannot be read or no Vision-capable "
                "model is currently available, explain the problem "
                "in plain language without exposing internal "
                "exception details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": _PATH_PARAMETER,
                    "instruction": _INSTRUCTION_PARAMETER,
                },
                "required": ["path"],
            },
        },
    ),
    VisionToolSpec(
        tool_capability_id="vision.analyze_diagram",
        provider_capability_id="vision.provider_analyze_diagram",
        tool_id="tool.vision_analyze_diagram",
        name="Vision - Analyze Diagram",
        tool_description=(
            "Orchestrates the Filesystem Capability and a "
            "Provider-backed Vision model to analyze a local "
            "architecture diagram, flowchart, or network diagram "
            "image."
        ),
        provider_description=(
            "AI-driven diagram analysis, satisfied by a Provider "
            "model specialized for vision understanding (e.g. "
            "`minicpm-v4.5`)."
        ),
        default_instruction=(
            "Explain this diagram: its type (e.g. flowchart, "
            "architecture, network diagram), its components, and how "
            "they relate to each other."
        ),
        question_argument=False,
        tool_affordance={
            "purpose": (
                "Analyzes an architecture diagram, flowchart, or "
                "network diagram image already stored locally."
            ),
            "use_when": (
                "the user wants a diagram explained (e.g. \"explain "
                "this architecture diagram\", \"describe this "
                "flowchart\", \"explain this network diagram\")."
            ),
            "avoid_when": (
                "the image is not a diagram (use "
                "`vision_describe_image` instead)."
            ),
            "requires": "the image file path; ask the user for it if not already known.",
            "result_semantics": (
                "Returns the diagram analysis. Present it directly, "
                "in prose, describing the components and their "
                "relationships."
            ),
            "failure_semantics": (
                "If the image cannot be read or no Vision-capable "
                "model is currently available, explain the problem "
                "in plain language without exposing internal "
                "exception details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": _PATH_PARAMETER,
                    "instruction": _INSTRUCTION_PARAMETER,
                },
                "required": ["path"],
            },
        },
    ),
    # `vision.detect_logos` and `vision.reason_about_image` (Phase 2/3
    # additions): both are purely Provider-backed -- no classical,
    # non-learned algorithm in this codebase can identify *which*
    # brand a logo belongs to, or perform open-ended reasoning/
    # inference about an image, so both take the exact same
    # "cheapest path" every Capability above already does: one more
    # `VisionToolSpec` entry, reusing `VisionToolDriver` completely
    # unmodified, zero new driver code.
    VisionToolSpec(
        tool_capability_id="vision.detect_logos",
        provider_capability_id="vision.provider_detect_logos",
        tool_id="tool.vision_detect_logos",
        name="Vision - Detect Logos",
        tool_description=(
            "Orchestrates the Filesystem Capability and a "
            "Provider-backed Vision model to detect and identify "
            "brand logos within a local image file."
        ),
        provider_description=(
            "AI-driven logo detection/brand identification, satisfied "
            "by a Provider model specialized for vision understanding "
            "(e.g. `minicpm-v4.5`). No classical, non-learned "
            "algorithm can identify *which* brand a logo belongs to, "
            "so this Capability is Provider-backed only, exactly like "
            "`vision.describe_image`."
        ),
        default_instruction=(
            "Detect every brand logo visible in this image and "
            "identify which brand each one belongs to."
        ),
        question_argument=False,
        tool_affordance={
            "purpose": "Detects and identifies brand logos within an image file already stored locally.",
            "use_when": "the user wants logos found or identified in an image (e.g. \"what brands appear in this photo\").",
            "avoid_when": "the user wants general object detection instead (use `vision_detect_objects`).",
            "requires": "the image file path; ask the user for it if not already known.",
            "result_semantics": "Returns the detected logos/brands. Present them directly.",
            "failure_semantics": (
                "If the image cannot be read or no Vision-capable "
                "model is currently available, explain the problem "
                "in plain language without exposing internal "
                "exception details."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": _PATH_PARAMETER, "instruction": _INSTRUCTION_PARAMETER},
                "required": ["path"],
            },
        },
    ),
    VisionToolSpec(
        tool_capability_id="vision.reason_about_image",
        provider_capability_id="vision.provider_reason_about_image",
        tool_id="tool.vision_reason_about_image",
        name="Vision - Reason About Image",
        tool_description=(
            "Orchestrates the Filesystem Capability and a "
            "Provider-backed Vision model to reason step by step "
            "about a local image file -- inferring context, cause, "
            "and implications beyond what is directly visible."
        ),
        provider_description=(
            "AI-driven open-ended visual reasoning/inference, "
            "satisfied by a Provider model specialized for vision "
            "understanding (e.g. `minicpm-v4.5`)."
        ),
        default_instruction=(
            "Reason step by step about what is happening in this "
            "image: infer likely context, cause, and implications "
            "beyond what is directly visible, explaining your "
            "reasoning."
        ),
        question_argument=False,
        tool_affordance={
            "purpose": (
                "Performs open-ended reasoning/inference about an "
                "image (why/how something happened, likely context) "
                "rather than merely describing what is visible."
            ),
            "use_when": (
                "the user wants inference or explanation beyond the "
                "literal contents (e.g. \"why do you think this "
                "happened\", \"what likely led to this\")."
            ),
            "avoid_when": (
                "the user wants a literal description instead (use "
                "`vision_describe_image`) or a specific factual "
                "question answered (use `vision_answer_question`)."
            ),
            "requires": "the image file path; ask the user for it if not already known.",
            "result_semantics": "Returns the reasoning. Present it directly, in prose.",
            "failure_semantics": (
                "If the image cannot be read or no Vision-capable "
                "model is currently available, explain the problem "
                "in plain language without exposing internal "
                "exception details."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": _PATH_PARAMETER, "instruction": _INSTRUCTION_PARAMETER},
                "required": ["path"],
            },
        },
    ),
)
"""
Every `vision.*` TOOL/Provider Capability pair the Vision Module
registers. Purely data -- see `VisionToolSpec`'s own docstring.
"""




class VisionModuleDriver(ModuleDriver):
    """
    Runtime driver for the Vision Module.
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

        vision_config = load_vision_config(configuration)
        self._enabled = vision_config.enabled

        def _progress_for(capability_id: str) -> ProgressReporter | None:
            return (
                ProgressReporter(event_bus, capability_id)
                if event_bus is not None
                else None
            )

        self._tool_drivers: dict[str, VisionToolDriver] = {
            spec.tool_capability_id: VisionToolDriver(
                brain=brain,
                provider_capability_id=spec.provider_capability_id,
                default_instruction=spec.default_instruction,
                question_argument=spec.question_argument,
                progress_reporter=_progress_for(spec.tool_capability_id),
            )
            for spec in _VISION_TOOL_SPECS
        }

        # Every deterministic-first Capability's own dedicated
        # ToolDriver (see `_VisionExtendedToolSpec`'s own docstring
        # for why these are not `VisionToolDriver` instances).
        self._extended_tool_drivers: dict[str, Any] = build_extended_tool_drivers(
            brain=brain,
            progress_for=_progress_for,
            vision_config=vision_config,
        )

    def start(self) -> None:
        if not self._enabled:
            self._logger.info(
                "Vision module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        for spec in _VISION_TOOL_SPECS:
            self._capability_registry.register(
                CapabilityDefinition(
                    id=spec.tool_capability_id,
                    name=spec.name,
                    description=spec.tool_description,
                    # TOOL, not VISION: Planner routes a Goal to
                    # ToolManager only when `category is
                    # CapabilityCategory.TOOL` (every other category
                    # is assumed to require a Provider model) -- and
                    # Automatic Capability Discovery only ever
                    # advertises TOOL-category Capabilities to the
                    # model (`ai_context/capability_context.py`). This
                    # Capability is backed by a real, deterministic-
                    # dispatch ToolDriver (`VisionToolDriver`), so it
                    # must be TOOL for either to work, exactly like
                    # `ocr.extract_text`.
                    category=CapabilityCategory.TOOL,
                    tags=frozenset({"vision", "image"}),
                    metadata={  # type: ignore[arg-type]
                        "tool_affordance": spec.tool_affordance
                    },
                )
            )
            self._tool_manager.register(
                Tool(
                    id=spec.tool_id,
                    name=spec.name,
                    version=VISION_TOOL_VERSION,
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
                    # LLM-family, Provider-routed -- never a Tool, and
                    # never advertised to the general chat model
                    # (never discovered by `capability_context
                    # .discover_capabilities()`'s TOOL-only filter),
                    # exactly like `ocr.provider_extract_text`.
                    category=CapabilityCategory.VISION,
                    tags=frozenset({"vision"}),
                )
            )

        for extended_spec in _VISION_EXTENDED_TOOL_SPECS:
            self._capability_registry.register(
                CapabilityDefinition(
                    id=extended_spec.tool_capability_id,
                    name=extended_spec.name,
                    description=extended_spec.tool_description,
                    category=CapabilityCategory.TOOL,
                    tags=frozenset({"vision", "image"}),
                    metadata={"tool_affordance": extended_spec.tool_affordance},  # type: ignore[arg-type]
                )
            )
            self._tool_manager.register(
                Tool(
                    id=extended_spec.tool_id,
                    name=extended_spec.name,
                    version=VISION_TOOL_VERSION,
                    description=extended_spec.tool_description,
                    capabilities=(extended_spec.tool_capability_id,),
                ),
                self._extended_tool_drivers[extended_spec.tool_capability_id],
            )

            if extended_spec.provider_capability_id is not None:
                self._capability_registry.register(
                    CapabilityDefinition(
                        id=extended_spec.provider_capability_id,
                        name=f"{extended_spec.name} (Provider)",
                        description=extended_spec.provider_description or "",
                        category=CapabilityCategory.VISION,
                        tags=frozenset({"vision"}),
                    )
                )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("Vision module started.")

    def stop(self) -> None:
        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        for spec in _VISION_TOOL_SPECS:
            self._tool_manager.unregister(spec.tool_id)
            self._capability_registry.unregister(spec.tool_capability_id)
            self._capability_registry.unregister(spec.provider_capability_id)

        for extended_spec in _VISION_EXTENDED_TOOL_SPECS:
            self._tool_manager.unregister(extended_spec.tool_id)
            self._capability_registry.unregister(extended_spec.tool_capability_id)

            if extended_spec.provider_capability_id is not None:
                self._capability_registry.unregister(
                    extended_spec.provider_capability_id
                )

        self._logger.info("Vision module stopped.")

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)
