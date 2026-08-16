"""
PARIKA Document Module - Driver

Implements the `ModuleDriver` contract for the Document Module,
following exactly the same "table-driven Tool specs, one driver class
per shape" pattern `OcrModuleDriver`/`VisionModuleDriver` already
establish. The Document Module becomes PARIKA's single entry point for
document processing, reusing the existing, unmodified OCR Module
whenever OCR is genuinely required and never performing OCR itself
(see `pipeline.py`/`engine.py`).

On start(), registers:

- Eleven Reading Capabilities (`document.extract_text` and the ten
  `document.read_*` Capabilities), each `CapabilityCategory.TOOL`,
  backed by `DocumentReadingToolDriver` (`driver_reading.py`). Purely
  deterministic - never a model call, and `document.extract_text`'s
  own PDF path is the *only* place this Module ever needs OCR, always
  delegated to the existing, unmodified `ocr.extract_text` Capability.
- Eight Extraction Capabilities (`document.extract_metadata`,
  `document.extract_images`, `document.extract_tables`,
  `document.extract_links`, `document.extract_headings`,
  `document.extract_sections`, `document.extract_references`,
  `document.extract_attachments`), each `CapabilityCategory.TOOL`,
  backed by `DocumentExtractionToolDriver` (`driver_extraction.py`).
  Also purely deterministic.
- Nine Provider-backed Analysis Capabilities (`document.summarize`,
  `document.answer_question`, `document.compare_documents`,
  `document.classify`, `document.detect_document_type`,
  `document.extract_entities`, `document.extract_action_items`,
  `document.extract_timeline`, `document.translate`), each
  `CapabilityCategory.TOOL`, backed by `DocumentAnalysisToolDriver`
  (`driver_analysis.py`), all sharing exactly one internal Provider
  Capability, `document.provider_analyze_content`
  (`CapabilityCategory.LLM`) - satisfied by whichever general-purpose
  text-generation Provider model the Model Selection Framework
  selects, never a hardcoded model name.
- Six deterministic Analysis Capabilities (`document.search`,
  `document.detect_language`, `document.extract_keywords`,
  `document.extract_dates`, `document.extract_contacts`,
  `document.detect_duplicates`), each `CapabilityCategory.TOOL`,
  backed by `DocumentDeterministicAnalysisToolDriver`
  (`driver_analysis_deterministic.py`). Never a model call - "never
  invoke an LLM if deterministic extraction is sufficient".

Thirty-four Tool Capabilities and one Provider Capability in total.
On stop(), unregisters all thirty-five.
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

from . import tool_affordances as affordances
from .config import DocumentToolConfig, load_document_config
from .driver_analysis import DocumentAnalysisToolDriver
from .driver_analysis_deterministic import DocumentDeterministicAnalysisToolDriver
from .driver_extraction import DocumentExtractionToolDriver
from .driver_reading import DocumentReadingToolDriver

DOCUMENT_TOOL_VERSION = "1.0.0"
MODULE_HEALTH_COMPONENT_ID = "module.document"

PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID = "document.provider_analyze_content"


@dataclass(frozen=True, slots=True, kw_only=True)
class _ReadingSpec:
    name: str
    """Suffix of the Capability id, e.g. `"extract_text"`, `"read_pdf"`."""

    expected_format: str | None
    """Fixed format for `document.read_*`; `None` for `document.extract_text` (auto-detect)."""

    tool_description: str
    tool_affordance: Mapping[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class _ExtractionSpec:
    facet: str
    tool_description: str
    tool_affordance: Mapping[str, Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class _AnalysisSpec:
    name: str
    tool_description: str
    default_instruction: str
    tool_affordance: Mapping[str, Any]
    question_argument: bool = False
    target_language_argument: bool = False
    second_document_argument: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class _DeterministicSpec:
    name: str
    tool_description: str
    tool_affordance: Mapping[str, Any]


_READING_SPECS: tuple[_ReadingSpec, ...] = (
    _ReadingSpec(
        name="extract_text",
        expected_format=None,
        tool_description=(
            "Universal entry point: auto-detects a local document's format "
            "(PDF, DOCX, PPTX, XLSX, Markdown, HTML, TXT, CSV, JSON, XML) "
            "and extracts its text, using the OCR Module internally only "
            "when a PDF has no usable native text layer."
        ),
        tool_affordance=affordances.DOCUMENT_EXTRACT_TEXT_TOOL_AFFORDANCE,
    ),
    _ReadingSpec(
        name="read_pdf",
        expected_format="pdf",
        tool_description="Reads a local PDF file's text (native text layer first, OCR Module fallback for scanned pages).",
        tool_affordance=affordances.READ_TOOL_AFFORDANCES["pdf"],
    ),
    _ReadingSpec(
        name="read_docx",
        expected_format="docx",
        tool_description="Reads a local Word (DOCX) file's text, headings, tables, and links.",
        tool_affordance=affordances.READ_TOOL_AFFORDANCES["docx"],
    ),
    _ReadingSpec(
        name="read_pptx",
        expected_format="pptx",
        tool_description="Reads a local PowerPoint (PPTX) file's slide text, tables, and notes.",
        tool_affordance=affordances.READ_TOOL_AFFORDANCES["pptx"],
    ),
    _ReadingSpec(
        name="read_xlsx",
        expected_format="xlsx",
        tool_description="Reads a local Excel (XLSX) file's sheets as tables.",
        tool_affordance=affordances.READ_TOOL_AFFORDANCES["xlsx"],
    ),
    _ReadingSpec(
        name="read_markdown",
        expected_format="markdown",
        tool_description="Reads a local Markdown file's text, headings, and links.",
        tool_affordance=affordances.READ_TOOL_AFFORDANCES["markdown"],
    ),
    _ReadingSpec(
        name="read_html",
        expected_format="html",
        tool_description="Reads a local HTML file's text, headings, links, images, and tables.",
        tool_affordance=affordances.READ_TOOL_AFFORDANCES["html"],
    ),
    _ReadingSpec(
        name="read_txt",
        expected_format="txt",
        tool_description="Reads a local plain-text file's content.",
        tool_affordance=affordances.READ_TOOL_AFFORDANCES["txt"],
    ),
    _ReadingSpec(
        name="read_csv",
        expected_format="csv",
        tool_description="Reads a local CSV file as a structured table.",
        tool_affordance=affordances.READ_TOOL_AFFORDANCES["csv"],
    ),
    _ReadingSpec(
        name="read_json",
        expected_format="json",
        tool_description="Reads a local JSON file's structured content.",
        tool_affordance=affordances.READ_TOOL_AFFORDANCES["json"],
    ),
    _ReadingSpec(
        name="read_xml",
        expected_format="xml",
        tool_description="Reads a local XML file's structured content.",
        tool_affordance=affordances.READ_TOOL_AFFORDANCES["xml"],
    ),
)

_EXTRACTION_SPECS: tuple[_ExtractionSpec, ...] = (
    _ExtractionSpec(
        facet="metadata",
        tool_description="Extracts a local document's metadata (title, author, dates, page/word count, language).",
        tool_affordance=affordances.EXTRACT_METADATA_TOOL_AFFORDANCE,
    ),
    _ExtractionSpec(
        facet="images",
        tool_description="Extracts a local document's embedded images' identity and location.",
        tool_affordance=affordances.EXTRACT_IMAGES_TOOL_AFFORDANCE,
    ),
    _ExtractionSpec(
        facet="tables",
        tool_description="Extracts a local document's tables as structured rows/columns.",
        tool_affordance=affordances.EXTRACT_TABLES_TOOL_AFFORDANCE,
    ),
    _ExtractionSpec(
        facet="links",
        tool_description="Extracts a local document's hyperlinks.",
        tool_affordance=affordances.EXTRACT_LINKS_TOOL_AFFORDANCE,
    ),
    _ExtractionSpec(
        facet="headings",
        tool_description="Extracts a local document's headings/outline.",
        tool_affordance=affordances.EXTRACT_HEADINGS_TOOL_AFFORDANCE,
    ),
    _ExtractionSpec(
        facet="sections",
        tool_description="Extracts a local document's content broken down by section.",
        tool_affordance=affordances.EXTRACT_SECTIONS_TOOL_AFFORDANCE,
    ),
    _ExtractionSpec(
        facet="references",
        tool_description="Extracts a local document's bibliography/citation references.",
        tool_affordance=affordances.EXTRACT_REFERENCES_TOOL_AFFORDANCE,
    ),
    _ExtractionSpec(
        facet="attachments",
        tool_description="Extracts a local document's embedded attachments/objects.",
        tool_affordance=affordances.EXTRACT_ATTACHMENTS_TOOL_AFFORDANCE,
    ),
)

_ANALYSIS_SPECS: tuple[_AnalysisSpec, ...] = (
    _AnalysisSpec(
        name="summarize",
        tool_description="Summarizes a local document's content using a Provider-backed language model.",
        default_instruction="Summarize this document concisely, preserving its key points.",
        tool_affordance=affordances.SUMMARIZE_TOOL_AFFORDANCE,
    ),
    _AnalysisSpec(
        name="answer_question",
        tool_description="Answers a specific question about a local document's content using a Provider-backed language model.",
        default_instruction="",
        question_argument=True,
        tool_affordance=affordances.ANSWER_QUESTION_TOOL_AFFORDANCE,
    ),
    _AnalysisSpec(
        name="compare_documents",
        tool_description="Compares two local documents' content using a Provider-backed language model.",
        default_instruction="Compare these two documents. Explain their key similarities and differences.",
        second_document_argument=True,
        tool_affordance=affordances.COMPARE_DOCUMENTS_TOOL_AFFORDANCE,
    ),
    _AnalysisSpec(
        name="classify",
        tool_description="Classifies a local document's topic/category using a Provider-backed language model.",
        default_instruction=(
            "Classify this document's topic/category. Respond with the "
            "category and a one-sentence rationale."
        ),
        tool_affordance=affordances.CLASSIFY_TOOL_AFFORDANCE,
    ),
    _AnalysisSpec(
        name="detect_document_type",
        tool_description="Infers a local document's real-world type (invoice, resume, contract, report, ...) using a Provider-backed language model.",
        default_instruction=(
            "Identify what real-world type of document this is (e.g. "
            "invoice, resume, contract, report, letter, form, article). "
            "Respond with the type and a one-sentence rationale."
        ),
        tool_affordance=affordances.DETECT_DOCUMENT_TYPE_TOOL_AFFORDANCE,
    ),
    _AnalysisSpec(
        name="extract_entities",
        tool_description="Extracts named entities mentioned in a local document using a Provider-backed language model.",
        default_instruction=(
            "Extract every named entity (people, organizations, "
            "locations, products, dates) mentioned in this document, "
            "grouped by type."
        ),
        tool_affordance=affordances.EXTRACT_ENTITIES_TOOL_AFFORDANCE,
    ),
    _AnalysisSpec(
        name="extract_action_items",
        tool_description="Extracts action items/tasks/follow-ups mentioned in a local document using a Provider-backed language model.",
        default_instruction=(
            "Extract every action item, task, or follow-up mentioned in "
            "this document, as a list. Include the owner/deadline when "
            "mentioned."
        ),
        tool_affordance=affordances.EXTRACT_ACTION_ITEMS_TOOL_AFFORDANCE,
    ),
    _AnalysisSpec(
        name="extract_timeline",
        tool_description="Builds a chronological timeline of events described in a local document using a Provider-backed language model.",
        default_instruction=(
            "Build a chronological timeline of the events described in "
            "this document, ordered earliest to latest."
        ),
        tool_affordance=affordances.EXTRACT_TIMELINE_TOOL_AFFORDANCE,
    ),
    _AnalysisSpec(
        name="translate",
        tool_description="Translates a local document's text into another language using a Provider-backed language model.",
        default_instruction="",
        target_language_argument=True,
        tool_affordance=affordances.TRANSLATE_TOOL_AFFORDANCE,
    ),
)

_DETERMINISTIC_SPECS: tuple[_DeterministicSpec, ...] = (
    _DeterministicSpec(
        name="search",
        tool_description="Searches a local document's extracted text for a literal string or regular expression.",
        tool_affordance=affordances.SEARCH_TOOL_AFFORDANCE,
    ),
    _DeterministicSpec(
        name="detect_language",
        tool_description="Detects the dominant language of a local document's text.",
        tool_affordance=affordances.DETECT_LANGUAGE_TOOL_AFFORDANCE,
    ),
    _DeterministicSpec(
        name="extract_keywords",
        tool_description="Extracts a local document's most frequent, meaningful terms.",
        tool_affordance=affordances.EXTRACT_KEYWORDS_TOOL_AFFORDANCE,
    ),
    _DeterministicSpec(
        name="extract_dates",
        tool_description="Extracts date mentions found in a local document's text.",
        tool_affordance=affordances.EXTRACT_DATES_TOOL_AFFORDANCE,
    ),
    _DeterministicSpec(
        name="extract_contacts",
        tool_description="Extracts contact details (emails, URLs, phone numbers) found in a local document's text.",
        tool_affordance=affordances.EXTRACT_CONTACTS_TOOL_AFFORDANCE,
    ),
    _DeterministicSpec(
        name="detect_duplicates",
        tool_description="Deterministically checks whether two local documents are identical or near-duplicates.",
        tool_affordance=affordances.DETECT_DUPLICATES_TOOL_AFFORDANCE,
    ),
)


class DocumentModuleDriver(ModuleDriver):
    """
    Runtime driver for the Document Module.
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

        document_config: DocumentToolConfig = load_document_config(configuration)
        self._enabled = document_config.enabled

        def _progress_for(capability_id: str) -> ProgressReporter | None:
            return ProgressReporter(event_bus, capability_id) if event_bus is not None else None

        self._reading_drivers: dict[str, DocumentReadingToolDriver] = {
            spec.name: DocumentReadingToolDriver(
                brain=brain,
                expected_format=spec.expected_format,
                progress_reporter=_progress_for(f"document.{spec.name}"),
            )
            for spec in _READING_SPECS
        }

        self._extraction_drivers: dict[str, DocumentExtractionToolDriver] = {
            spec.facet: DocumentExtractionToolDriver(
                brain=brain,
                facet=spec.facet,
                progress_reporter=_progress_for(f"document.extract_{spec.facet}"),
                config=document_config,
            )
            for spec in _EXTRACTION_SPECS
        }

        self._analysis_drivers: dict[str, DocumentAnalysisToolDriver] = {
            spec.name: DocumentAnalysisToolDriver(
                brain=brain,
                provider_capability_id=PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID,
                default_instruction=spec.default_instruction,
                question_argument=spec.question_argument,
                target_language_argument=spec.target_language_argument,
                second_document_argument=spec.second_document_argument,
                progress_reporter=_progress_for(f"document.{spec.name}"),
            )
            for spec in _ANALYSIS_SPECS
        }

        self._deterministic_drivers: dict[str, DocumentDeterministicAnalysisToolDriver] = {
            spec.name: DocumentDeterministicAnalysisToolDriver(
                brain=brain,
                kind=spec.name,
                progress_reporter=_progress_for(f"document.{spec.name}"),
                config=document_config,
            )
            for spec in _DETERMINISTIC_SPECS
        }

    def start(self) -> None:
        if not self._enabled:
            self._logger.info(
                "Document module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        for spec in _READING_SPECS:
            self._register_tool(
                capability_id=f"document.{spec.name}",
                tool_id=f"tool.document_{spec.name}",
                name=f"Document - {spec.name.replace('_', ' ').title()}",
                description=spec.tool_description,
                tool_affordance=spec.tool_affordance,
                driver=self._reading_drivers[spec.name],
            )

        for spec in _EXTRACTION_SPECS:
            self._register_tool(
                capability_id=f"document.extract_{spec.facet}",
                tool_id=f"tool.document_extract_{spec.facet}",
                name=f"Document - Extract {spec.facet.title()}",
                description=spec.tool_description,
                tool_affordance=spec.tool_affordance,
                driver=self._extraction_drivers[spec.facet],
            )

        for spec in _ANALYSIS_SPECS:
            self._register_tool(
                capability_id=f"document.{spec.name}",
                tool_id=f"tool.document_{spec.name}",
                name=f"Document - {spec.name.replace('_', ' ').title()}",
                description=spec.tool_description,
                tool_affordance=spec.tool_affordance,
                driver=self._analysis_drivers[spec.name],
            )

        for spec in _DETERMINISTIC_SPECS:
            self._register_tool(
                capability_id=f"document.{spec.name}",
                tool_id=f"tool.document_{spec.name}",
                name=f"Document - {spec.name.replace('_', ' ').title()}",
                description=spec.tool_description,
                tool_affordance=spec.tool_affordance,
                driver=self._deterministic_drivers[spec.name],
            )

        self._capability_registry.register(
            CapabilityDefinition(
                id=PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID,
                name="Document - Provider Analyze Content",
                description=(
                    "AI-driven semantic reasoning over already-extracted "
                    "document text, satisfied by a general-purpose "
                    "text-generation Provider model. Shared, unmodified, "
                    "by every Analysis Tool in this Module that genuinely "
                    "needs semantic reasoning (summarize, answer_question, "
                    "compare_documents, classify, detect_document_type, "
                    "extract_entities, extract_action_items, "
                    "extract_timeline, translate) - never duplicated per "
                    "Tool, exactly like `ocr.provider_extract_text`."
                ),
                # LLM-family, Provider-routed -- never a Tool, and never
                # advertised to the general chat model (never discovered
                # by `capability_context.discover_capabilities()`'s
                # TOOL-only filter), exactly like `ocr.provider_extract_text`/
                # `vision.provider_*`/`coding.plan_change`.
                category=CapabilityCategory.LLM,
                tags=frozenset({"document"}),
            )
        )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("Document module started.")

    def stop(self) -> None:
        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._capability_registry.unregister(PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID)

        for spec in _DETERMINISTIC_SPECS:
            self._unregister_tool(f"tool.document_{spec.name}", f"document.{spec.name}")

        for spec in _ANALYSIS_SPECS:
            self._unregister_tool(f"tool.document_{spec.name}", f"document.{spec.name}")

        for spec in _EXTRACTION_SPECS:
            self._unregister_tool(
                f"tool.document_extract_{spec.facet}", f"document.extract_{spec.facet}"
            )

        for spec in _READING_SPECS:
            self._unregister_tool(f"tool.document_{spec.name}", f"document.{spec.name}")

        self._logger.info("Document module stopped.")

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _register_tool(
        self,
        *,
        capability_id: str,
        tool_id: str,
        name: str,
        description: str,
        tool_affordance: Mapping[str, Any],
        driver: object,
    ) -> None:
        self._capability_registry.register(
            CapabilityDefinition(
                id=capability_id,
                name=name,
                description=description,
                # TOOL, not LLM: Planner routes a Goal to ToolManager only
                # when `category is CapabilityCategory.TOOL` (every other
                # category is assumed to require a Provider model) -- and
                # Automatic Capability Discovery only ever advertises
                # TOOL-category Capabilities to the model
                # (`ai_context/capability_context.py`). Every Capability
                # this Module registers here is backed by a real,
                # deterministic-dispatch ToolDriver, so it must be TOOL for
                # either to work, exactly like `ocr.extract_text`/
                # `vision.describe_image`.
                category=CapabilityCategory.TOOL,
                tags=frozenset({"document"}),
                metadata={"tool_affordance": tool_affordance},  # type: ignore[arg-type]
            )
        )
        self._tool_manager.register(
            Tool(
                id=tool_id,
                name=name,
                version=DOCUMENT_TOOL_VERSION,
                description=description,
                capabilities=(capability_id,),
            ),
            driver,  # type: ignore[arg-type]
        )

    def _unregister_tool(self, tool_id: str, capability_id: str) -> None:
        self._tool_manager.unregister(tool_id)
        self._capability_registry.unregister(capability_id)
