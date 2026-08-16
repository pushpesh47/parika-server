"""
PARIKA Document Module - Document Pipeline

The single, shared "obtain a `UnifiedDocument` for this path" function
every Reading, Extraction, and (single-document) Analysis Tool in this
Module calls -- extracted once here so `driver_reading.py`,
`driver_extraction.py`, and `driver_analysis.py`/
`driver_analysis_deterministic.py` all share exactly one
implementation of the Document Pipeline the spec describes:

    Filesystem -> determine document type -> native parser available?
    -> YES: extract structured content / NO: OCR fallback -> merge ->
    unified document representation.

Mirrors `parika/modules/ocr/engine.py`'s own "extract the shared
nested-Goal steps once" precedent.
"""

from __future__ import annotations

from . import format_detection, readers
from .document_model import DocumentMetadata, DocumentPage, UnifiedDocument
from .engine import ocr_extract_text, read_document_bytes, read_document_text
from .exceptions import DocumentFormatError

_TEXT_READERS = {
    "markdown": readers.read_markdown,
    "html": readers.read_html,
    "txt": readers.read_txt,
    "csv": readers.read_csv,
    "json": readers.read_json,
    "xml": readers.read_xml,
}

_BINARY_READERS = {
    "docx": readers.read_docx,
    "pptx": readers.read_pptx,
    "xlsx": readers.read_xlsx,
}


def resolve_format(path: str, expected_format: str | None) -> str:
    document_format = expected_format or format_detection.detect_format_from_path(path)

    if document_format is None:
        raise DocumentFormatError(
            f"Could not determine the document format of '{path}' from its "
            f"extension. Supported formats: "
            f"{', '.join(format_detection.SUPPORTED_FORMATS)}."
        )

    return document_format


def parse_document(
    brain: object,
    path: str,
    document_format: str,
    *,
    execution_requirements: object = None,
) -> UnifiedDocument:
    """
    Parse `path` (already known to be `document_format`) into a
    `UnifiedDocument`:

    - `pdf`: delegated entirely to the existing, unmodified
      `ocr.extract_text` Capability (never re-implemented here).
    - Text-native formats: read via `filesystem.read(binary=False)`,
      then parsed deterministically (`readers.py`).
    - Office Open XML formats: read via `filesystem.read(binary=True)`,
      then parsed deterministically by the optional
      `python-docx`/`python-pptx`/`openpyxl` dependency
      (`config.py`'s graceful degradation).
    """

    if document_format == "pdf":
        return _parse_pdf(brain, path, execution_requirements)

    if document_format in _TEXT_READERS:
        text = read_document_text(brain, path)
        return _TEXT_READERS[document_format](text)

    if document_format in _BINARY_READERS:
        data = read_document_bytes(brain, path)
        return _BINARY_READERS[document_format](data)

    raise DocumentFormatError(f"Unsupported document format: '{document_format}'.")


def resolve_and_parse(
    brain: object, path: str, expected_format: str | None, *, execution_requirements: object = None
) -> UnifiedDocument:
    """`resolve_format()` followed by `parse_document()` -- the common case."""

    document_format = resolve_format(path, expected_format)
    return parse_document(
        brain, path, document_format, execution_requirements=execution_requirements
    )


def _parse_pdf(brain: object, path: str, execution_requirements: object) -> UnifiedDocument:
    result = ocr_extract_text(brain, path, execution_requirements=execution_requirements)  # type: ignore[arg-type]

    raw_pages = result.get("pages")

    if isinstance(raw_pages, list) and raw_pages:
        pages = tuple(
            DocumentPage(
                page_number=int(raw_page.get("page", index + 1)),
                text=str(raw_page.get("text", "")),
                source="native" if raw_page.get("source") == "text_layer" else "ocr",
            )
            for index, raw_page in enumerate(raw_pages)
        )
    else:
        pages = (
            DocumentPage(page_number=1, text=str(result.get("text", "")), source="ocr"),
        )

    text = str(result.get("text", ""))

    return UnifiedDocument(
        format="pdf",
        text=text,
        metadata=DocumentMetadata(
            page_count=len(pages),
            word_count=len(text.split()),
            character_count=len(text),
        ),
        pages=pages,
    )
