"""
PARIKA Document Module - Native Format Readers

One deterministic parser per supported format (`format_detection
.SUPPORTED_FORMATS`), each mapping its format's own native structure
into the provider-independent `UnifiedDocument` (`document_model.py`) -
"all providers should map into this unified model" the spec requires,
generalized here to "all native format parsers".

Local processing first, exactly as the spec's own preferred order
states: stdlib parsers for text-native formats (txt, csv, json, xml,
and a stdlib-only fallback for markdown/html), then the optional,
gracefully-degrading `python-docx`/`python-pptx`/`openpyxl`/
`beautifulsoup4` libraries for the Office Open XML formats and richer
HTML parsing (`config.py`). PDF has no reader here at all - text
extraction for `pdf` is delegated entirely to the existing, unmodified
`ocr.extract_text` Capability (see `engine.ocr_extract_text()` and
`driver_reading.py`'s own PDF branch), never re-implemented.

Never calls a Provider model. Never performs OCR itself.
"""

from __future__ import annotations

import csv
import io
import json
import re
from xml.etree import ElementTree

from . import config
from .document_model import (
    DocumentHeading,
    DocumentImage,
    DocumentLink,
    DocumentMetadata,
    DocumentPage,
    DocumentSection,
    DocumentTable,
    UnifiedDocument,
)
from .exceptions import DocumentParseError

_MARKDOWN_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _word_count(text: str) -> int:
    return len(text.split())


def _sections_from_line_headings(
    text: str, headings: list[tuple[int, DocumentHeading]]
) -> tuple[DocumentSection, ...]:
    """
    Split `text` into `DocumentSection`s using each heading's
    character offset -- shared by the Markdown and (fallback) HTML
    readers, both of which locate headings by regex offset in the raw
    text rather than a structured document tree.
    """

    if not headings:
        return (DocumentSection(heading=None, text=text.strip()),) if text.strip() else ()

    sections: list[DocumentSection] = []

    if headings[0][0] > 0:
        leading = text[: headings[0][0]].strip()

        if leading:
            sections.append(DocumentSection(heading=None, text=leading))

    for index, (offset, heading) in enumerate(headings):
        end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
        sections.append(DocumentSection(heading=heading, text=text[offset:end].strip()))

    return tuple(sections)


# ----------------------------------------------------------------------
# Text-native formats (stdlib only)
# ----------------------------------------------------------------------


def read_txt(text: str) -> UnifiedDocument:
    return UnifiedDocument(
        format="txt",
        text=text,
        metadata=DocumentMetadata(
            word_count=_word_count(text), character_count=len(text)
        ),
        pages=(DocumentPage(page_number=1, text=text),),
    )


def read_markdown(text: str) -> UnifiedDocument:
    headings: list[tuple[int, DocumentHeading]] = []

    for match in _MARKDOWN_HEADING_PATTERN.finditer(text):
        level = len(match.group(1))
        headings.append(
            (match.start(), DocumentHeading(level=level, text=match.group(2).strip()))
        )

    links = tuple(
        DocumentLink(text=match.group(1), url=match.group(2))
        for match in _MARKDOWN_LINK_PATTERN.finditer(text)
    )

    return UnifiedDocument(
        format="markdown",
        text=text,
        markdown=text,
        metadata=DocumentMetadata(
            word_count=_word_count(text), character_count=len(text)
        ),
        pages=(DocumentPage(page_number=1, text=text),),
        headings=tuple(heading for _, heading in headings),
        sections=_sections_from_line_headings(text, headings),
        links=links,
    )


def read_csv(text: str) -> UnifiedDocument:
    try:
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect=dialect)
    rows = [tuple(row) for row in reader]

    headers = rows[0] if rows else ()
    data_rows = tuple(rows[1:]) if len(rows) > 1 else ()

    structured = [dict(zip(headers, row)) for row in data_rows] if headers else []
    rendered = "\n".join(", ".join(row) for row in rows)

    return UnifiedDocument(
        format="csv",
        text=rendered,
        structured={"rows": structured} if structured else {"rows": []},
        metadata=DocumentMetadata(
            word_count=_word_count(rendered),
            character_count=len(rendered),
            extra={"row_count": len(rows)},
        ),
        pages=(DocumentPage(page_number=1, text=rendered),),
        tables=(DocumentTable(headers=headers, rows=data_rows),) if rows else (),
    )


def read_json(text: str) -> UnifiedDocument:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as ex:
        raise DocumentParseError(f"Could not parse JSON: {ex}") from ex

    rendered = json.dumps(data, indent=2, ensure_ascii=False)

    return UnifiedDocument(
        format="json",
        text=rendered,
        structured=data if isinstance(data, dict) else {"value": data},
        metadata=DocumentMetadata(
            word_count=_word_count(rendered), character_count=len(rendered)
        ),
        pages=(DocumentPage(page_number=1, text=rendered),),
    )


def read_xml(text: str) -> UnifiedDocument:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as ex:
        raise DocumentParseError(f"Could not parse XML: {ex}") from ex

    structured = _xml_element_to_dict(root)
    flattened_text = " ".join(
        piece.strip() for piece in root.itertext() if piece and piece.strip()
    )

    return UnifiedDocument(
        format="xml",
        text=flattened_text,
        structured={root.tag: structured},
        metadata=DocumentMetadata(
            word_count=_word_count(flattened_text),
            character_count=len(flattened_text),
        ),
        pages=(DocumentPage(page_number=1, text=flattened_text),),
    )


def _xml_element_to_dict(element: ElementTree.Element) -> object:
    children = list(element)

    if not children:
        return (element.text or "").strip()

    result: dict[str, object] = {}

    for child in children:
        value = _xml_element_to_dict(child)

        if child.tag in result:
            existing = result[child.tag]

            if isinstance(existing, list):
                existing.append(value)
            else:
                result[child.tag] = [existing, value]
        else:
            result[child.tag] = value

    if element.attrib:
        result["@attributes"] = dict(element.attrib)

    return result


# ----------------------------------------------------------------------
# HTML (best-effort stdlib fallback, richer with the optional `bs4`)
# ----------------------------------------------------------------------


def read_html(text: str) -> UnifiedDocument:
    if config.html_parsing_dependency_available():
        return _read_html_with_bs4(text)

    return _read_html_stdlib(text)


def _read_html_with_bs4(text: str) -> UnifiedDocument:
    from bs4 import BeautifulSoup  # type: ignore[import-untyped]

    soup = BeautifulSoup(text, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    headings: list[DocumentHeading] = []

    for level in range(1, 7):
        for tag in soup.find_all(f"h{level}"):
            headings.append(DocumentHeading(level=level, text=tag.get_text(strip=True)))

    links = tuple(
        DocumentLink(text=tag.get_text(strip=True), url=str(tag.get("href")))
        for tag in soup.find_all("a")
        if tag.get("href")
    )

    images = tuple(
        DocumentImage(
            index=index,
            content_type="image/unknown",
            description=str(tag.get("alt")) if tag.get("alt") else None,
        )
        for index, tag in enumerate(soup.find_all("img"))
    )

    tables: list[DocumentTable] = []

    for table_tag in soup.find_all("table"):
        rows_data = [
            tuple(cell.get_text(strip=True) for cell in row.find_all(["td", "th"]))
            for row in table_tag.find_all("tr")
        ]

        if not rows_data:
            continue

        header, *body = rows_data
        tables.append(DocumentTable(headers=header, rows=tuple(body)))

    body_text = soup.get_text(separator="\n", strip=True)

    return UnifiedDocument(
        format="html",
        text=body_text,
        metadata=DocumentMetadata(
            title=title,
            word_count=_word_count(body_text),
            character_count=len(body_text),
        ),
        pages=(DocumentPage(page_number=1, text=body_text),),
        headings=tuple(headings),
        links=links,
        images=images,
        tables=tuple(tables),
    )


_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_HTML_TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HTML_HEADING_PATTERN = re.compile(
    r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL
)
_HTML_LINK_PATTERN = re.compile(
    r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)


def _read_html_stdlib(text: str) -> UnifiedDocument:
    """
    Best-effort HTML extraction with no third-party dependency at all
    - regex-based, not a real DOM, but sufficient for headings/links/
    plain text when the optional `beautifulsoup4` dependency is not
    installed. Never a crash.
    """

    title_match = _HTML_TITLE_PATTERN.search(text)
    title = _strip_tags(title_match.group(1)).strip() if title_match else None

    headings: list[tuple[int, DocumentHeading]] = []

    for match in _HTML_HEADING_PATTERN.finditer(text):
        headings.append(
            (
                match.start(),
                DocumentHeading(
                    level=int(match.group(1)), text=_strip_tags(match.group(2)).strip()
                ),
            )
        )

    links = tuple(
        DocumentLink(text=_strip_tags(match.group(2)).strip(), url=match.group(1))
        for match in _HTML_LINK_PATTERN.finditer(text)
    )

    body_text = _strip_tags(text)

    return UnifiedDocument(
        format="html",
        text=body_text,
        metadata=DocumentMetadata(
            title=title, word_count=_word_count(body_text), character_count=len(body_text)
        ),
        pages=(DocumentPage(page_number=1, text=body_text),),
        headings=tuple(heading for _, heading in headings),
        sections=_sections_from_line_headings(body_text, []),
        links=links,
    )


def _strip_tags(html: str) -> str:
    without_tags = _HTML_TAG_PATTERN.sub(" ", html)
    return re.sub(r"[ \t]+", " ", without_tags).strip()


# ----------------------------------------------------------------------
# Office Open XML formats (optional dependencies, graceful degradation)
# ----------------------------------------------------------------------


def read_docx(data: bytes) -> UnifiedDocument:
    config.require_docx()

    import docx  # type: ignore[import-untyped]

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as ex:
        raise DocumentParseError(f"Could not parse DOCX: {ex}") from ex

    headings: list[DocumentHeading] = []
    paragraphs: list[str] = []

    for paragraph in document.paragraphs:
        style_name = (paragraph.style.name or "") if paragraph.style else ""
        text = paragraph.text

        if not text.strip():
            continue

        heading_match = re.match(r"^Heading\s*(\d)$", style_name.strip(), re.IGNORECASE)
        title_match = style_name.strip().lower() == "title"

        if heading_match:
            headings.append(
                DocumentHeading(level=int(heading_match.group(1)), text=text.strip())
            )
        elif title_match:
            headings.append(DocumentHeading(level=1, text=text.strip()))

        paragraphs.append(text)

    full_text = "\n".join(paragraphs)

    tables = tuple(
        DocumentTable(
            headers=tuple(cell.text.strip() for cell in table.rows[0].cells)
            if table.rows
            else (),
            rows=tuple(
                tuple(cell.text.strip() for cell in row.cells)
                for row in table.rows[1:]
            ),
        )
        for table in document.tables
    )

    links = _extract_docx_hyperlinks(document)
    images = _extract_docx_images(document)

    core_properties = document.core_properties

    return UnifiedDocument(
        format="docx",
        text=full_text,
        metadata=DocumentMetadata(
            title=core_properties.title or None,
            author=core_properties.author or None,
            subject=core_properties.subject or None,
            created=str(core_properties.created) if core_properties.created else None,
            modified=str(core_properties.modified) if core_properties.modified else None,
            word_count=_word_count(full_text),
            character_count=len(full_text),
        ),
        pages=(DocumentPage(page_number=1, text=full_text),),
        headings=tuple(headings),
        sections=_sections_from_paragraph_headings(paragraphs, headings),
        tables=tables,
        links=links,
        images=images,
    )


def _sections_from_paragraph_headings(
    paragraphs: list[str], headings: list[DocumentHeading]
) -> tuple[DocumentSection, ...]:
    """
    Best-effort section split for DOCX: matches each heading's own
    text against the paragraph stream (headings are a subset of
    `paragraphs`) rather than tracking offsets directly, since
    `python-docx` does not expose character offsets.
    """

    if not headings:
        return ()

    heading_texts = {heading.text for heading in headings}
    sections: list[DocumentSection] = []
    current_heading: DocumentHeading | None = None
    current_lines: list[str] = []

    for line in paragraphs:
        if line in heading_texts and current_heading is None and not current_lines:
            current_heading = next(h for h in headings if h.text == line)
            continue

        if line in heading_texts:
            sections.append(
                DocumentSection(heading=current_heading, text="\n".join(current_lines))
            )
            current_heading = next(h for h in headings if h.text == line)
            current_lines = []
            continue

        current_lines.append(line)

    sections.append(DocumentSection(heading=current_heading, text="\n".join(current_lines)))

    return tuple(sections)


def _extract_docx_hyperlinks(document: object) -> tuple[DocumentLink, ...]:
    """
    Best-effort hyperlink extraction: `python-docx` exposes no public
    hyperlink API, so this walks each paragraph's own XML for
    `w:hyperlink` elements and resolves their relationship id against
    the document part's relationships. Never raises - any XML shape
    this cannot handle simply yields no links for that paragraph.
    """

    links: list[DocumentLink] = []

    try:
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        relationship_namespace = (
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
        )

        for paragraph in document.paragraphs:  # type: ignore[attr-defined]
            for hyperlink_element in paragraph._p.findall(f".//{namespace}hyperlink"):
                relationship_id = hyperlink_element.get(f"{relationship_namespace}id")

                if not relationship_id:
                    continue

                try:
                    url = document.part.rels[relationship_id].target_ref  # type: ignore[attr-defined]
                except KeyError:
                    continue

                text = "".join(
                    node.text or ""
                    for node in hyperlink_element.findall(f".//{namespace}t")
                )

                if text.strip() and url:
                    links.append(DocumentLink(text=text.strip(), url=url))
    except Exception:
        return tuple(links)

    return tuple(links)


def _extract_docx_images(document: object) -> tuple[DocumentImage, ...]:
    images: list[DocumentImage] = []

    try:
        for index, shape in enumerate(document.inline_shapes):  # type: ignore[attr-defined]
            content_type = "image/unknown"

            try:
                image_part = shape._inline.graphic.graphicData.pic.blipFill.blip
                relationship_id = image_part.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
                )
                part = document.part.rels[relationship_id].target_part  # type: ignore[attr-defined]
                content_type = part.content_type
            except Exception:
                pass

            images.append(DocumentImage(index=index, content_type=content_type))
    except Exception:
        return tuple(images)

    return tuple(images)


def read_pptx(data: bytes) -> UnifiedDocument:
    config.require_pptx()

    from pptx import Presentation  # type: ignore[import-untyped]

    try:
        presentation = Presentation(io.BytesIO(data))
    except Exception as ex:
        raise DocumentParseError(f"Could not parse PPTX: {ex}") from ex

    pages: list[DocumentPage] = []
    headings: list[DocumentHeading] = []
    tables: list[DocumentTable] = []
    images: list[DocumentImage] = []
    all_text: list[str] = []
    image_index = 0

    for slide_index, slide in enumerate(presentation.slides, start=1):
        slide_lines: list[str] = []

        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in paragraph.runs)

                    if not text.strip():
                        continue

                    slide_lines.append(text)

                    if shape == slide.shapes.title:
                        headings.append(DocumentHeading(level=1, text=text.strip()))

            if shape.has_table:
                table = shape.table
                rows_data = [
                    tuple(cell.text.strip() for cell in row.cells) for row in table.rows
                ]

                if rows_data:
                    header, *body = rows_data
                    tables.append(
                        DocumentTable(
                            headers=header, rows=tuple(body), page=slide_index
                        )
                    )

            if shape.shape_type == 13:  # MSO_SHAPE_TYPE.PICTURE
                images.append(
                    DocumentImage(
                        index=image_index, content_type="image/unknown", page=slide_index
                    )
                )
                image_index += 1

        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            slide_lines.append(f"[Notes] {slide.notes_slide.notes_text_frame.text}")

        slide_text = "\n".join(slide_lines)
        pages.append(DocumentPage(page_number=slide_index, text=slide_text))
        all_text.append(slide_text)

    full_text = "\n\n".join(all_text)

    return UnifiedDocument(
        format="pptx",
        text=full_text,
        metadata=DocumentMetadata(
            page_count=len(pages),
            word_count=_word_count(full_text),
            character_count=len(full_text),
        ),
        pages=tuple(pages),
        headings=tuple(headings),
        tables=tuple(tables),
        images=tuple(images),
    )


def read_xlsx(data: bytes) -> UnifiedDocument:
    config.require_xlsx()

    import openpyxl  # type: ignore[import-untyped]

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    except Exception as ex:
        raise DocumentParseError(f"Could not parse XLSX: {ex}") from ex

    pages: list[DocumentPage] = []
    tables: list[DocumentTable] = []
    all_text: list[str] = []

    for sheet_index, sheet_name in enumerate(workbook.sheetnames, start=1):
        sheet = workbook[sheet_name]
        rows_data = [
            tuple("" if cell is None else str(cell) for cell in row)
            for row in sheet.iter_rows(values_only=True)
        ]

        header = rows_data[0] if rows_data else ()
        body = tuple(rows_data[1:]) if len(rows_data) > 1 else ()

        if rows_data:
            tables.append(DocumentTable(headers=header, rows=body, page=sheet_index))

        sheet_text = "\n".join(", ".join(row) for row in rows_data)
        pages.append(
            DocumentPage(page_number=sheet_index, text=f"[{sheet_name}]\n{sheet_text}")
        )
        all_text.append(sheet_text)

    workbook.close()
    full_text = "\n\n".join(all_text)

    return UnifiedDocument(
        format="xlsx",
        text=full_text,
        metadata=DocumentMetadata(
            page_count=len(pages),
            word_count=_word_count(full_text),
            character_count=len(full_text),
            extra={"sheet_names": list(workbook.sheetnames)},
        ),
        pages=tuple(pages),
        tables=tuple(tables),
    )
