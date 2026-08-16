"""
PARIKA Document Module - Exceptions
"""

from __future__ import annotations


class DocumentError(Exception):
    """Base exception for every Document Module failure."""


class DocumentReadError(DocumentError):
    """
    Raised when the referenced document could not be obtained through
    the existing, unmodified `filesystem.read` Capability (e.g. the
    path does not exist, is not readable), or when a required Tool
    argument (e.g. `path`) was missing.
    """


class DocumentFormatError(DocumentError):
    """
    Raised when a document's format could not be determined, or when
    a Tool that requires a specific format (e.g. `document.read_pdf`)
    was given a file that is clearly a different format.
    """


class DocumentParseError(DocumentError):
    """
    Raised when a native, deterministic parser (python-docx,
    python-pptx, openpyxl, an XML/HTML/CSV/JSON parser, ...) could not
    parse an otherwise-readable file (e.g. it is corrupted).
    """


class DocumentDependencyUnavailableError(DocumentError):
    """
    Raised when a deterministic Document feature is invoked while its
    optional dependency group is not installed (see
    `parika/modules/document/config.py`). `document.extract_text` on
    text-native formats (txt/markdown/html/csv/json/xml) never raises
    this - only the office-format parsers that depend on the optional
    `document` extra (`pyproject.toml`) do.
    """


class DocumentOcrFallbackError(DocumentError):
    """
    Raised when the nested, Tool-backed `ocr.extract_text` Goal this
    Module delegates to for scanned/image-only content did not
    succeed (e.g. the OCR Module is disabled, or no OCR-capable
    Provider model is currently available).
    """


class DocumentAnalysisError(DocumentError):
    """
    Raised when a nested, Provider-backed `document.provider_analyze_content`
    Goal (summarize, answer_question, compare_documents, classify,
    detect_document_type, extract_entities, extract_action_items,
    extract_timeline, translate) did not succeed (e.g. no suitable
    Provider model is currently available/enabled).
    """
