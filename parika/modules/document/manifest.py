"""
PARIKA Document Module - Manifest

Defines the static ModuleManifest describing the Document Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .module_driver import DocumentModuleDriver

DOCUMENT_MODULE_ID = "document"
DOCUMENT_MODULE_VERSION = "1.0.0"


def create_document_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Document Module.
    """

    return ModuleManifest(
        id=DOCUMENT_MODULE_ID,
        name="Document",
        version=DOCUMENT_MODULE_VERSION,
        description=(
            "PARIKA's single entry point for document understanding: "
            "reading (`document.extract_text` and ten format-specific "
            "`document.read_*` Capabilities for PDF/DOCX/PPTX/XLSX/"
            "Markdown/HTML/TXT/CSV/JSON/XML), structural extraction "
            "(metadata/images/tables/links/headings/sections/references/"
            "attachments), and semantic analysis (summarize, "
            "answer_question, compare_documents, search, classify, "
            "detect_language, detect_document_type, extract_entities, "
            "extract_keywords, extract_action_items, extract_dates, "
            "extract_contacts, extract_timeline, translate, "
            "detect_duplicates). Orchestrates native, deterministic "
            "parsing first and delegates to the existing, unmodified "
            "OCR Module (`ocr.extract_text`) only when a PDF has no "
            "usable native text layer -- this Module never performs "
            "OCR itself. Semantic reasoning is satisfied by one shared "
            "internal Capability, `document.provider_analyze_content` "
            "(`CapabilityCategory.LLM`), never advertised directly to "
            "the general chat model, mirroring the OCR/Vision Modules' "
            "own Tool-orchestrator + Provider-backed shape exactly."
        ),
        author="PARIKA",
        license="MIT",
        tags=("document", "pdf", "docx", "pptx", "xlsx", "text"),
        driver="parika.modules.document.module_driver.DocumentModuleDriver",
    )


def create_document_module(driver: DocumentModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Document Module.

    Args:
        driver:
            Constructed DocumentModuleDriver instance for this module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=DOCUMENT_MODULE_ID,
        manifest=create_document_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
