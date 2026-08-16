"""
Unit tests for the OCR Module's PDF page support
(`parika.modules.ocr.pdf_support`). Uses real, minimal, hand-built
PDF byte strings and the real `pypdfium2` dependency - never a
Provider, never Brain/Goal.
"""

from __future__ import annotations

import pytest

from parika.modules.ocr.exceptions import OcrPdfError
from parika.modules.ocr.pdf_support import is_pdf, render_pdf_pages

_TEXT_PAGE_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 58>>stream
BT /F1 24 Tf 20 100 Td (Hello PARIKA OCR) Tj ET
endstream
endobj
trailer
<</Size 6/Root 1 0 R>>
%%EOF"""

_BLANK_PAGE_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj
trailer
<</Size 4/Root 1 0 R>>
%%EOF"""


class TestIsPdf:
    def test_recognizes_pdf_signature(self) -> None:
        assert is_pdf(_TEXT_PAGE_PDF)

    def test_rejects_non_pdf_bytes(self) -> None:
        assert not is_pdf(b"not a pdf at all")

    def test_rejects_empty_bytes(self) -> None:
        assert not is_pdf(b"")


class TestRenderPdfPages:
    def test_page_with_text_layer_is_not_rendered_to_an_image(self) -> None:
        pages = render_pdf_pages(_TEXT_PAGE_PDF, min_text_layer_chars=5)

        assert len(pages) == 1
        assert pages[0].page_number == 1
        assert pages[0].has_text_layer
        assert "Hello PARIKA OCR" in pages[0].text_layer
        assert pages[0].image is None

    def test_page_without_text_layer_is_rendered_to_an_image(self) -> None:
        pages = render_pdf_pages(_BLANK_PAGE_PDF, min_text_layer_chars=5)

        assert len(pages) == 1
        assert not pages[0].has_text_layer
        assert pages[0].image is not None

    def test_render_images_false_skips_rendering_even_without_text_layer(
        self,
    ) -> None:
        pages = render_pdf_pages(
            _BLANK_PAGE_PDF, min_text_layer_chars=5, render_images=False
        )

        assert not pages[0].has_text_layer
        assert pages[0].image is None

    def test_min_text_layer_chars_controls_the_text_vs_image_decision(self) -> None:
        # "Hello PARIKA OCR" is 16 characters - below a threshold of
        # 100, it must be treated as "no usable text layer" and
        # rendered instead.
        pages = render_pdf_pages(_TEXT_PAGE_PDF, min_text_layer_chars=100)

        assert not pages[0].has_text_layer
        assert pages[0].image is not None

    def test_invalid_pdf_bytes_raise_ocr_pdf_error(self) -> None:
        with pytest.raises(OcrPdfError):
            render_pdf_pages(b"this is definitely not a pdf")
