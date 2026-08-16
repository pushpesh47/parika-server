"""
PARIKA Document Module package.

PARIKA's single entry point for document processing: orchestrates
native document parsing, OCR fallback (delegated entirely to the
existing, unmodified OCR Module), metadata/structure extraction, and
semantic document analysis, into PARIKA through ModuleManager,
CapabilityRegistry, and ToolManager -- following exactly the same
Tool-orchestrator + Provider-backed shape the OCR and Vision Modules
already established.

Thirty-four public `document.*` TOOL Capabilities (Reading: `extract_text`
plus ten format-specific `read_*`; Extraction: `extract_metadata`,
`extract_images`, `extract_tables`, `extract_links`, `extract_headings`,
`extract_sections`, `extract_references`, `extract_attachments`;
Analysis: `summarize`, `answer_question`, `compare_documents`, `search`,
`classify`, `detect_language`, `detect_document_type`,
`extract_entities`, `extract_keywords`, `extract_action_items`,
`extract_dates`, `extract_contacts`, `extract_timeline`, `translate`,
`detect_duplicates`), plus one shared internal Provider Capability,
`document.provider_analyze_content`.
"""

from __future__ import annotations

from .config import DocumentToolConfig, load_document_config
from .document_model import UnifiedDocument
from .exceptions import (
    DocumentAnalysisError,
    DocumentDependencyUnavailableError,
    DocumentError,
    DocumentFormatError,
    DocumentOcrFallbackError,
    DocumentParseError,
    DocumentReadError,
)
from .manifest import (
    DOCUMENT_MODULE_ID,
    DOCUMENT_MODULE_VERSION,
    create_document_module,
    create_document_module_manifest,
)
from .module_driver import (
    MODULE_HEALTH_COMPONENT_ID,
    PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID,
    DocumentModuleDriver,
)

__all__ = [
    "DOCUMENT_MODULE_ID",
    "DOCUMENT_MODULE_VERSION",
    "MODULE_HEALTH_COMPONENT_ID",
    "PROVIDER_ANALYZE_CONTENT_CAPABILITY_ID",
    "DocumentAnalysisError",
    "DocumentDependencyUnavailableError",
    "DocumentError",
    "DocumentFormatError",
    "DocumentModuleDriver",
    "DocumentOcrFallbackError",
    "DocumentParseError",
    "DocumentReadError",
    "DocumentToolConfig",
    "UnifiedDocument",
    "create_document_module",
    "create_document_module_manifest",
    "load_document_config",
]
