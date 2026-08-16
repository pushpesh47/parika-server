"""
PARIKA Document Module - Unified Document Model

A provider-independent, deterministic, in-memory representation every
native format parser (`readers.py`) and the OCR-fallback path
(`engine.py`) map into, so every downstream Tool (extraction,
analysis) reads exactly one shape regardless of which format produced
it - the "unified document representation" the Document Module exists
to return.

Every dataclass here is frozen/slots/kw_only, mirroring every other
Core/Module domain object in this codebase (see
`parika/modules/ocr/pdf_support.py`'s `PdfPage`,
`parika/modules/ocr/document_types.py`'s `DocumentTypeTemplate`).
Nothing here performs parsing, I/O, or a Provider/model call itself -
this module is pure data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentHeading:
    """One heading, at any level, anywhere in the document."""

    level: int
    """1 = top-level (e.g. H1/Heading 1/`#`), 2 = subheading, etc."""

    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentSection:
    """
    One section: the text between one heading and the next of equal
    or higher level (or the document's start/end for the first/last
    section). `heading` is `None` for any leading, un-headed content.
    """

    heading: DocumentHeading | None
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentTable:
    """One table's rows, as already-extracted string cells."""

    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    page: int | None = None
    """1-indexed page/slide/sheet number, when the format has one."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentImage:
    """One embedded image's identity - never its raw bytes."""

    index: int
    """0-indexed position among this document's embedded images."""

    content_type: str
    """e.g. `"image/png"`, `"image/jpeg"`."""

    page: int | None = None
    description: str | None = None
    """Alt text/caption, when the format carries one (e.g. HTML `alt`)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentLink:
    """One hyperlink."""

    text: str
    url: str
    page: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentPage:
    """
    One page/slide/sheet, when the format has a natural notion of one
    (PDF pages, PPTX slides, XLSX sheets). Formats with no such notion
    (TXT, Markdown, HTML, CSV, JSON, XML, DOCX) report a single page.
    """

    page_number: int
    text: str
    source: str = "native"
    """`"native"` (deterministic parser) or `"ocr"` (OCR Module fallback)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentMetadata:
    """Provider-independent metadata common across formats."""

    title: str | None = None
    author: str | None = None
    subject: str | None = None
    created: str | None = None
    modified: str | None = None
    language: str | None = None
    page_count: int | None = None
    word_count: int = 0
    character_count: int = 0
    extra: "dict[str, object]" = field(default_factory=dict)
    """Format-specific metadata that does not fit a common field above."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UnifiedDocument:
    """
    The single, provider-independent internal document representation
    every native parser and the OCR-fallback path map into.

    Fields deliberately mirror the spec's own "Unified Document
    Model" list: metadata, pages, sections, headings, paragraphs
    (`text`, newline-joined), tables, images, links, references,
    extracted text, language, document type (`format`).
    """

    format: str
    """One of the Document Module's supported format names (e.g. `"pdf"`, `"docx"`)."""

    text: str
    """The complete, flattened extracted text -- every reader's baseline output."""

    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    pages: tuple[DocumentPage, ...] = field(default_factory=tuple)
    sections: tuple[DocumentSection, ...] = field(default_factory=tuple)
    headings: tuple[DocumentHeading, ...] = field(default_factory=tuple)
    tables: tuple[DocumentTable, ...] = field(default_factory=tuple)
    images: tuple[DocumentImage, ...] = field(default_factory=tuple)
    links: tuple[DocumentLink, ...] = field(default_factory=tuple)
    markdown: str | None = None
    """Best-effort Markdown rendering, when the reader produces one."""

    structured: "dict[str, object] | None" = None
    """Best-effort structured JSON (e.g. parsed CSV/JSON/XML), when applicable."""

    def to_result_dict(self) -> "dict[str, object]":
        """
        The common `ToolResponse.result` shape every reading/
        extraction Tool in this Module builds on top of - a plain,
        JSON-serializable dict, never the dataclass itself.
        """

        return {
            "format": self.format,
            "text": self.text,
            "markdown": self.markdown,
            "structured": self.structured,
            "metadata": {
                "title": self.metadata.title,
                "author": self.metadata.author,
                "subject": self.metadata.subject,
                "created": self.metadata.created,
                "modified": self.metadata.modified,
                "language": self.metadata.language,
                "page_count": self.metadata.page_count,
                "word_count": self.metadata.word_count,
                "character_count": self.metadata.character_count,
                **dict(self.metadata.extra),
            },
            "pages": [
                {"page": page.page_number, "text": page.text, "source": page.source}
                for page in self.pages
            ],
            "headings": [
                {"level": heading.level, "text": heading.text}
                for heading in self.headings
            ],
            "sections": [
                {
                    "heading": (
                        {"level": section.heading.level, "text": section.heading.text}
                        if section.heading is not None
                        else None
                    ),
                    "text": section.text,
                }
                for section in self.sections
            ],
            "tables": [
                {
                    "headers": list(table.headers),
                    "rows": [list(row) for row in table.rows],
                    "page": table.page,
                }
                for table in self.tables
            ],
            "images": [
                {
                    "index": image.index,
                    "content_type": image.content_type,
                    "page": image.page,
                    "description": image.description,
                }
                for image in self.images
            ],
            "links": [
                {"text": link.text, "url": link.url, "page": link.page}
                for link in self.links
            ],
        }
