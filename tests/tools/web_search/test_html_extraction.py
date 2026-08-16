"""
Unit tests for Web Search Tool HTML extraction helpers.
"""

from __future__ import annotations

from parika.tools.web_search.html_extraction import (
    extract_meta_description,
    extract_text,
    extract_title,
)

SAMPLE_HTML = """
<html>
<head>
<title>Example Domain</title>
<meta name="description" content="Example description text.">
<style>body { color: red; }</style>
<script>console.log("ignored");</script>
</head>
<body>
<h1>Example Domain</h1>
<p>This domain is for use in illustrative examples.</p>
</body>
</html>
"""


class TestExtractTitle:
    def test_extracts_title(self) -> None:
        assert extract_title(SAMPLE_HTML) == "Example Domain"

    def test_returns_none_when_missing(self) -> None:
        assert extract_title("<html><body>No title</body></html>") is None


class TestExtractMetaDescription:
    def test_extracts_description(self) -> None:
        assert (
            extract_meta_description(SAMPLE_HTML)
            == "Example description text."
        )

    def test_returns_none_when_missing(self) -> None:
        assert (
            extract_meta_description("<html><head></head></html>") is None
        )

    def test_supports_og_description_fallback(self) -> None:
        html = (
            "<html><head>"
            '<meta property="og:description" content="OG text.">'
            "</head></html>"
        )

        assert extract_meta_description(html) == "OG text."


class TestExtractText:
    def test_extracts_visible_text(self) -> None:
        text = extract_text(SAMPLE_HTML)

        assert "Example Domain" in text
        assert "illustrative examples" in text

    def test_excludes_script_and_style_content(self) -> None:
        text = extract_text(SAMPLE_HTML)

        assert "console.log" not in text
        assert "color: red" not in text

    def test_empty_document_returns_empty_string(self) -> None:
        assert extract_text("<html></html>") == ""
