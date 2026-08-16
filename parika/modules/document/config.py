"""
PARIKA Document Module - Configuration

Reads the `[document]` configuration section and detects, at runtime,
whether each optional native-format dependency is installed:
`python-docx` (DOCX), `python-pptx` (PPTX), `openpyxl` (XLSX), and
`beautifulsoup4`/`lxml` (richer HTML parsing). Mirrors exactly the
pattern `parika/modules/ocr/config.py` already establishes for the
`ocr` extra.

Text-native formats (`txt`, `markdown`, `csv`, `json`, `xml`, and a
best-effort stdlib fallback for `html`) never depend on any of this -
every format that requires an optional dependency degrades gracefully
(never a crash) when it is not installed; callers check the relevant
`*_available` property first and raise a typed
`DocumentDependencyUnavailableError` with an actionable message,
exactly like `OcrToolConfig` does for the `ocr` extra.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

from .exceptions import DocumentDependencyUnavailableError

DEFAULT_ENABLED = True
DEFAULT_MAX_REFERENCE_CANDIDATES = 200
DEFAULT_MAX_KEYWORDS = 15
DEFAULT_SEARCH_CONTEXT_CHARS = 80


def docx_dependency_available() -> bool:
    """Whether the optional `python-docx` dependency is installed."""

    return importlib.util.find_spec("docx") is not None


def pptx_dependency_available() -> bool:
    """Whether the optional `python-pptx` dependency is installed."""

    return importlib.util.find_spec("pptx") is not None


def xlsx_dependency_available() -> bool:
    """Whether the optional `openpyxl` dependency is installed."""

    return importlib.util.find_spec("openpyxl") is not None


def html_parsing_dependency_available() -> bool:
    """
    Whether the optional `beautifulsoup4` dependency is installed. A
    stdlib `html.parser`-based fallback is always available for basic
    text/link/heading extraction when it is not.
    """

    return importlib.util.find_spec("bs4") is not None


def language_detection_dependency_available() -> bool:
    """
    Whether the (base, non-optional) `langdetect` dependency is
    installed - reused by `document.detect_language` exactly as the
    OCR Module reuses it for `ocr.detect_language`.
    """

    return importlib.util.find_spec("langdetect") is not None


def require_docx() -> None:
    if not docx_dependency_available():
        raise DocumentDependencyUnavailableError(
            "Reading DOCX files requires the optional 'document' "
            "dependency group (python-docx) to be installed."
        )


def require_pptx() -> None:
    if not pptx_dependency_available():
        raise DocumentDependencyUnavailableError(
            "Reading PPTX files requires the optional 'document' "
            "dependency group (python-pptx) to be installed."
        )


def require_xlsx() -> None:
    if not xlsx_dependency_available():
        raise DocumentDependencyUnavailableError(
            "Reading XLSX files requires the optional 'document' "
            "dependency group (openpyxl) to be installed."
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentToolConfig:
    """
    Immutable, typed snapshot of `[document]` configuration.
    """

    enabled: bool = DEFAULT_ENABLED
    max_reference_candidates: int = DEFAULT_MAX_REFERENCE_CANDIDATES
    max_keywords: int = DEFAULT_MAX_KEYWORDS
    search_context_chars: int = DEFAULT_SEARCH_CONTEXT_CHARS

    @property
    def docx_available(self) -> bool:
        return docx_dependency_available()

    @property
    def pptx_available(self) -> bool:
        return pptx_dependency_available()

    @property
    def xlsx_available(self) -> bool:
        return xlsx_dependency_available()

    @property
    def html_parsing_available(self) -> bool:
        return html_parsing_dependency_available()

    @property
    def language_detection_available(self) -> bool:
        return language_detection_dependency_available()


def load_document_config(configuration: Configuration | None) -> DocumentToolConfig:
    """
    Build a `DocumentToolConfig` snapshot from `Configuration`.
    """

    if configuration is None:
        return DocumentToolConfig()

    return DocumentToolConfig(
        enabled=bool(configuration.get("document.enabled", DEFAULT_ENABLED)),
        max_reference_candidates=int(
            configuration.get(
                "document.max_reference_candidates",
                DEFAULT_MAX_REFERENCE_CANDIDATES,
            )
        ),
        max_keywords=int(
            configuration.get("document.max_keywords", DEFAULT_MAX_KEYWORDS)
        ),
        search_context_chars=int(
            configuration.get(
                "document.search_context_chars", DEFAULT_SEARCH_CONTEXT_CHARS
            )
        ),
    )
