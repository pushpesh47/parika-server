"""
PARIKA OCR Module - PDF Page Support

Deterministic PDF page handling for the OCR Module's PDF-aware tools
(`driver.py`'s `ocr.extract_text`, `structured_driver.py`'s
`document.extract_text`): per page, first attempts a zero-cost,
deterministic text-layer extraction (`pypdfium2`'s own text page API)
- if the PDF already carries real, extractable text (a "born-digital"
PDF), no image rendering and no OCR/model call is ever needed for
that page at all. Only pages with no/insufficient extractable text (a
scanned or image-only page) are rendered to a Pillow `Image` for the
existing image OCR pipeline (`preprocessing.py`/`engine.py`) to
consume - directly satisfying "avoid duplicate OCR passes" and
treating "OCR scanned PDFs" and "OCR image-only PDFs" as the genuinely
distinct paths they are, rather than always paying for a model call
per page.

Requires the optional `pypdfium2` dependency (`pyproject.toml`'s `ocr`
extra); raises `OcrDependencyUnavailableError` when it is not
installed, and `OcrPdfError` when `pdf_bytes` cannot be parsed as a
PDF at all - the same gracefully-degrading, dedicated-exception
contract `preprocessing.py` establishes for its own optional
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .exceptions import OcrDependencyUnavailableError, OcrPdfError

if TYPE_CHECKING:
    from PIL.Image import Image

DEFAULT_RENDER_DPI = 200
DEFAULT_MIN_TEXT_LAYER_CHARS = 20

_PDF_MAGIC = b"%PDF-"
_POINTS_PER_INCH = 72.0


def _require_pdf() -> None:
    from .config import pdf_dependency_available

    if not pdf_dependency_available():
        raise OcrDependencyUnavailableError(
            "PDF support requires the optional 'ocr' dependency group "
            "(pypdfium2) to be installed."
        )


def is_pdf(data: bytes) -> bool:
    """Sniff whether `data` begins with a PDF file signature (`%PDF-`)."""

    return data[: len(_PDF_MAGIC)] == _PDF_MAGIC


@dataclass(frozen=True, slots=True, kw_only=True)
class PdfPage:
    """
    One PDF page. `page_number` is 1-indexed, so it can be surfaced
    verbatim in results - preserving document page numbering end to
    end, as the spec requires.
    """

    page_number: int
    text_layer: str
    has_text_layer: bool
    image: "Image | None"


def render_pdf_pages(
    pdf_bytes: bytes,
    *,
    dpi: int = DEFAULT_RENDER_DPI,
    min_text_layer_chars: int = DEFAULT_MIN_TEXT_LAYER_CHARS,
    render_images: bool = True,
) -> tuple[PdfPage, ...]:
    """
    Parse `pdf_bytes` and, for every page, attempt deterministic
    text-layer extraction first. Only render a page to an `Image`
    (when `render_images` is True) if its extracted text layer is
    shorter than `min_text_layer_chars` - i.e. it is a scanned/
    image-only page with no usable text layer already, so it
    genuinely needs the OCR/model pipeline.

    Raises:
        OcrDependencyUnavailableError:
            If the optional `pypdfium2` dependency is not installed.
        OcrPdfError:
            If `pdf_bytes` cannot be parsed as a PDF at all.
    """

    _require_pdf()

    import pypdfium2 as pdfium  # type: ignore[import-untyped]

    try:
        document = pdfium.PdfDocument(pdf_bytes)
    except Exception as ex:
        raise OcrPdfError(f"Could not parse PDF: {ex}") from ex

    try:
        scale = dpi / _POINTS_PER_INCH
        pages: list[PdfPage] = []

        for index in range(len(document)):
            page = document[index]

            try:
                text_page = page.get_textpage()
                text_layer = text_page.get_text_range().strip()
                text_page.close()
            except Exception:
                text_layer = ""

            has_text_layer = len(text_layer) >= min_text_layer_chars
            image: "Image | None" = None

            if render_images and not has_text_layer:
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                bitmap.close()

            page.close()

            pages.append(
                PdfPage(
                    page_number=index + 1,
                    text_layer=text_layer,
                    has_text_layer=has_text_layer,
                    image=image,
                )
            )

        return tuple(pages)
    finally:
        document.close()
