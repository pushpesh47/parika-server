from __future__ import annotations

from parika.modules.document import format_detection


class TestDetectFormatFromPath:
    def test_recognizes_every_supported_extension(self) -> None:
        assert format_detection.detect_format_from_path("/a/b/report.pdf") == "pdf"
        assert format_detection.detect_format_from_path("/a/b/report.DOCX") == "docx"
        assert format_detection.detect_format_from_path("/a/b/slides.pptx") == "pptx"
        assert format_detection.detect_format_from_path("/a/b/sheet.xlsx") == "xlsx"
        assert format_detection.detect_format_from_path("/a/b/notes.md") == "markdown"
        assert format_detection.detect_format_from_path("/a/b/notes.markdown") == "markdown"
        assert format_detection.detect_format_from_path("/a/b/page.html") == "html"
        assert format_detection.detect_format_from_path("/a/b/page.htm") == "html"
        assert format_detection.detect_format_from_path("/a/b/readme.txt") == "txt"
        assert format_detection.detect_format_from_path("/a/b/data.csv") == "csv"
        assert format_detection.detect_format_from_path("/a/b/data.json") == "json"
        assert format_detection.detect_format_from_path("/a/b/data.xml") == "xml"

    def test_unrecognized_extension_returns_none(self) -> None:
        assert format_detection.detect_format_from_path("/a/b/image.png") is None
        assert format_detection.detect_format_from_path("/a/b/no_extension") is None


class TestDetectFormatFromBytes:
    def test_sniffs_pdf_magic_bytes(self) -> None:
        assert format_detection.detect_format_from_bytes(b"%PDF-1.7\n...") == "pdf"

    def test_sniffs_zip_magic_bytes(self) -> None:
        assert format_detection.detect_format_from_bytes(b"PK\x03\x04rest") == "zip"

    def test_unrecognized_bytes_return_none(self) -> None:
        assert format_detection.detect_format_from_bytes(b"plain text") is None


class TestResolveFormat:
    def test_prefers_extension_over_sniff(self) -> None:
        assert format_detection.resolve_format("/a/report.pdf", sniffed_bytes=b"not a pdf") == "pdf"

    def test_falls_back_to_pdf_sniff_when_extension_unknown(self) -> None:
        assert format_detection.resolve_format("/a/report", sniffed_bytes=b"%PDF-1.7") == "pdf"

    def test_returns_none_when_neither_resolves(self) -> None:
        assert format_detection.resolve_format("/a/report", sniffed_bytes=b"plain text") is None
