"""
PARIKA OCR Module - Driver

Implements the `ModuleDriver` contract for the OCR Module, following
exactly the same two-Capability shape `CodingAgentModuleDriver`
already establishes for the Coding Agent
(`parika/modules/coding_agent/module_driver.py`):

On start(), registers:
- `ocr.extract_text` (`CapabilityCategory.TOOL`) with its
  `tool.ocr_extract_text` Tool -- advertised to the general chat model
  through Automatic Capability Discovery/its own Tool Affordance
  Contract, exactly like `coding.execute_task`.
- `ocr.provider_extract_text` (`CapabilityCategory.OCR`) -- satisfied
  by a Provider model (e.g. `glm-ocr`), never a Tool, and never
  advertised directly to the general chat model (Automatic Capability
  Discovery only ever discovers TOOL-category Capabilities -- see
  `parika/interfaces/ai_context/capability_context.py`), exactly like
  `coding.plan_change`.
- Six further TOOL Capabilities (`ocr.detect_orientation`,
  `ocr.detect_quality`, `ocr.detect_language`, `ocr.extract_layout`,
  `ocr.extract_table`, `ocr.extract_form`), each with its own Tool --
  every one of them reuses this same `ocr.provider_extract_text`
  Provider Capability internally where a model call is genuinely
  needed (never a new Provider Capability per Tool; see
  `structured_driver.py`'s own module docstring for why), or needs no
  model call at all (`ocr.detect_orientation`/`ocr.detect_quality`,
  fully deterministic).

On stop(), unregisters all eight.

`document.extract_text` (formerly a temporary implementation detail
of this Module) has moved to the first-class Document Module
(`parika/modules/document/`), which reuses `ocr.extract_text`
internally for scanned/image-only PDFs rather than duplicating any
OCR logic.
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

from .analysis_driver import OcrOrientationToolDriver, OcrQualityToolDriver
from .config import OcrToolConfig, load_ocr_config
from .driver import OcrToolDriver
from .structured_driver import OcrFormToolDriver, OcrTableToolDriver
from .text_tools_driver import OcrLanguageToolDriver, OcrLayoutToolDriver
from .tool_affordances import (
    OCR_DETECT_LANGUAGE_TOOL_AFFORDANCE,
    OCR_DETECT_ORIENTATION_TOOL_AFFORDANCE,
    OCR_DETECT_QUALITY_TOOL_AFFORDANCE,
    OCR_EXTRACT_FORM_TOOL_AFFORDANCE,
    OCR_EXTRACT_LAYOUT_TOOL_AFFORDANCE,
    OCR_EXTRACT_TABLE_TOOL_AFFORDANCE,
    OCR_EXTRACT_TEXT_TOOL_AFFORDANCE,
)

EXTRACT_TEXT_CAPABILITY_ID = "ocr.extract_text"
PROVIDER_EXTRACT_TEXT_CAPABILITY_ID = "ocr.provider_extract_text"
EXTRACT_TEXT_TOOL_ID = "tool.ocr_extract_text"

DETECT_ORIENTATION_CAPABILITY_ID = "ocr.detect_orientation"
DETECT_QUALITY_CAPABILITY_ID = "ocr.detect_quality"
DETECT_LANGUAGE_CAPABILITY_ID = "ocr.detect_language"
EXTRACT_LAYOUT_CAPABILITY_ID = "ocr.extract_layout"
EXTRACT_TABLE_CAPABILITY_ID = "ocr.extract_table"
EXTRACT_FORM_CAPABILITY_ID = "ocr.extract_form"

DETECT_ORIENTATION_TOOL_ID = "tool.ocr_detect_orientation"
DETECT_QUALITY_TOOL_ID = "tool.ocr_detect_quality"
DETECT_LANGUAGE_TOOL_ID = "tool.ocr_detect_language"
EXTRACT_LAYOUT_TOOL_ID = "tool.ocr_extract_layout"
EXTRACT_TABLE_TOOL_ID = "tool.ocr_extract_table"
EXTRACT_FORM_TOOL_ID = "tool.ocr_extract_form"

OCR_TOOL_VERSION = "1.0.0"

MODULE_HEALTH_COMPONENT_ID = "module.ocr"


@dataclass(frozen=True, slots=True, kw_only=True)
class _OcrExtendedToolSpec:
    """One of the six additional OCR Tool Capabilities' static registration data."""

    tool_capability_id: str
    tool_id: str
    name: str
    tool_description: str
    tool_affordance: Mapping[str, Any]


class OcrModuleDriver(ModuleDriver):
    """
    Runtime driver for the OCR Module.
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

        ocr_config: OcrToolConfig = load_ocr_config(configuration)
        self._enabled = ocr_config.enabled

        def _progress_for(capability_id: str) -> ProgressReporter | None:
            return ProgressReporter(event_bus, capability_id) if event_bus is not None else None

        self._tool_driver = OcrToolDriver(
            brain=brain,
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
            progress_reporter=_progress_for(EXTRACT_TEXT_CAPABILITY_ID),
            config=ocr_config,
        )

        self._extended_tool_drivers: dict[str, Any] = {
            DETECT_ORIENTATION_CAPABILITY_ID: OcrOrientationToolDriver(
                brain=brain,
                progress_reporter=_progress_for(DETECT_ORIENTATION_CAPABILITY_ID),
                config=ocr_config,
            ),
            DETECT_QUALITY_CAPABILITY_ID: OcrQualityToolDriver(
                brain=brain,
                progress_reporter=_progress_for(DETECT_QUALITY_CAPABILITY_ID),
                config=ocr_config,
            ),
            DETECT_LANGUAGE_CAPABILITY_ID: OcrLanguageToolDriver(
                brain=brain,
                recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
                progress_reporter=_progress_for(DETECT_LANGUAGE_CAPABILITY_ID),
                config=ocr_config,
            ),
            EXTRACT_LAYOUT_CAPABILITY_ID: OcrLayoutToolDriver(
                brain=brain,
                recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
                progress_reporter=_progress_for(EXTRACT_LAYOUT_CAPABILITY_ID),
            ),
            EXTRACT_TABLE_CAPABILITY_ID: OcrTableToolDriver(
                brain=brain,
                recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
                progress_reporter=_progress_for(EXTRACT_TABLE_CAPABILITY_ID),
                config=ocr_config,
            ),
            EXTRACT_FORM_CAPABILITY_ID: OcrFormToolDriver(
                brain=brain,
                recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
                progress_reporter=_progress_for(EXTRACT_FORM_CAPABILITY_ID),
            ),
        }

    def start(self) -> None:
        if not self._enabled:
            self._logger.info(
                "OCR module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        self._capability_registry.register(
            CapabilityDefinition(
                id=EXTRACT_TEXT_CAPABILITY_ID,
                name="OCR - Extract Text",
                description=(
                    "Orchestrates the Filesystem Capability and a "
                    "Provider-backed OCR model to extract text from a "
                    "local image or PDF file."
                ),
                # TOOL, not OCR: Planner routes a Goal to ToolManager
                # only when `category is CapabilityCategory.TOOL`
                # (every other category is assumed to require a
                # Provider model) -- and Automatic Capability
                # Discovery only ever advertises TOOL-category
                # Capabilities to the model
                # (`ai_context/capability_context.py`). This
                # Capability is backed by a real, deterministic-
                # dispatch ToolDriver (`OcrToolDriver`), so it must be
                # TOOL for either to work, exactly like
                # `coding.execute_task`.
                category=CapabilityCategory.TOOL,
                tags=frozenset({"ocr", "vision", "image"}),
                metadata={  # type: ignore[arg-type]
                    "tool_affordance": OCR_EXTRACT_TEXT_TOOL_AFFORDANCE
                },
            )
        )
        self._tool_manager.register(
            Tool(
                id=EXTRACT_TEXT_TOOL_ID,
                name="OCR Extract Text",
                version=OCR_TOOL_VERSION,
                description="Extracts text from a local image or PDF file via OCR.",
                capabilities=(EXTRACT_TEXT_CAPABILITY_ID,),
            ),
            self._tool_driver,
        )

        self._capability_registry.register(
            CapabilityDefinition(
                id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
                name="OCR - Provider Extract Text",
                description=(
                    "AI-driven text recognition over an already-"
                    "obtained image, satisfied by a Provider model "
                    "specialized for OCR (e.g. `glm-ocr`). Reused, "
                    "unmodified, by every Tool in this Module that "
                    "genuinely needs a model call (extract_text, "
                    "detect_language's path fallback, extract_layout's "
                    "path fallback, extract_table, extract_form), and "
                    "also reused, unmodified, by the Document Module's "
                    "`document.extract_text` for scanned/image-only "
                    "PDFs -- never duplicated per caller."
                ),
                # LLM-family, Provider-routed -- never a Tool, and
                # never advertised to the general chat model (never
                # discovered by `capability_context
                # .discover_capabilities()`'s TOOL-only filter),
                # exactly like `coding.plan_change`.
                category=CapabilityCategory.OCR,
                tags=frozenset({"ocr", "vision"}),
            )
        )

        for spec in _OCR_EXTENDED_TOOL_SPECS:
            self._capability_registry.register(
                CapabilityDefinition(
                    id=spec.tool_capability_id,
                    name=spec.name,
                    description=spec.tool_description,
                    category=CapabilityCategory.TOOL,
                    tags=frozenset({"ocr", "vision", "image"}),
                    metadata={"tool_affordance": spec.tool_affordance},  # type: ignore[arg-type]
                )
            )
            self._tool_manager.register(
                Tool(
                    id=spec.tool_id,
                    name=spec.name,
                    version=OCR_TOOL_VERSION,
                    description=spec.tool_description,
                    capabilities=(spec.tool_capability_id,),
                ),
                self._extended_tool_drivers[spec.tool_capability_id],
            )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("OCR module started.")

    def stop(self) -> None:
        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        for spec in _OCR_EXTENDED_TOOL_SPECS:
            self._tool_manager.unregister(spec.tool_id)
            self._capability_registry.unregister(spec.tool_capability_id)

        self._tool_manager.unregister(EXTRACT_TEXT_TOOL_ID)
        self._capability_registry.unregister(EXTRACT_TEXT_CAPABILITY_ID)
        self._capability_registry.unregister(PROVIDER_EXTRACT_TEXT_CAPABILITY_ID)

        self._logger.info("OCR module stopped.")

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)


_OCR_EXTENDED_TOOL_SPECS: tuple[_OcrExtendedToolSpec, ...] = (
    _OcrExtendedToolSpec(
        tool_capability_id=DETECT_ORIENTATION_CAPABILITY_ID,
        tool_id=DETECT_ORIENTATION_TOOL_ID,
        name="OCR - Detect Orientation",
        tool_description=(
            "Deterministically estimates an image's page rotation "
            "(0/90/180/270 degrees). Never calls a model."
        ),
        tool_affordance=OCR_DETECT_ORIENTATION_TOOL_AFFORDANCE,
    ),
    _OcrExtendedToolSpec(
        tool_capability_id=DETECT_QUALITY_CAPABILITY_ID,
        tool_id=DETECT_QUALITY_TOOL_ID,
        name="OCR - Detect Quality",
        tool_description=(
            "Deterministically assesses a document image's OCR "
            "readability (resolution, sharpness, contrast). Never "
            "calls a model."
        ),
        tool_affordance=OCR_DETECT_QUALITY_TOOL_AFFORDANCE,
    ),
    _OcrExtendedToolSpec(
        tool_capability_id=DETECT_LANGUAGE_CAPABILITY_ID,
        tool_id=DETECT_LANGUAGE_TOOL_ID,
        name="OCR - Detect Language",
        tool_description=(
            "Detects the dominant language of already-recognized text "
            "or an image's text."
        ),
        tool_affordance=OCR_DETECT_LANGUAGE_TOOL_AFFORDANCE,
    ),
    _OcrExtendedToolSpec(
        tool_capability_id=EXTRACT_LAYOUT_CAPABILITY_ID,
        tool_id=EXTRACT_LAYOUT_TOOL_ID,
        name="OCR - Extract Layout",
        tool_description=(
            "Extracts text and its structural layout (lines, "
            "paragraphs, probable headings) from already-recognized "
            "text or an image."
        ),
        tool_affordance=OCR_EXTRACT_LAYOUT_TOOL_AFFORDANCE,
    ),
    _OcrExtendedToolSpec(
        tool_capability_id=EXTRACT_TABLE_CAPABILITY_ID,
        tool_id=EXTRACT_TABLE_TOOL_ID,
        name="OCR - Extract Table",
        tool_description="Extracts a table's rows/columns from an image as structured data.",
        tool_affordance=OCR_EXTRACT_TABLE_TOOL_AFFORDANCE,
    ),
    _OcrExtendedToolSpec(
        tool_capability_id=EXTRACT_FORM_CAPABILITY_ID,
        tool_id=EXTRACT_FORM_TOOL_ID,
        name="OCR - Extract Form",
        tool_description=(
            "Extracts a form's labeled fields/key-value pairs from an "
            "image as structured data."
        ),
        tool_affordance=OCR_EXTRACT_FORM_TOOL_AFFORDANCE,
    ),
)
