from __future__ import annotations

from parika.modules.document import readers
from parika.modules.document.exceptions import DocumentParseError


class TestReadTxt:
    def test_returns_text_verbatim(self) -> None:
        document = readers.read_txt("hello world")

        assert document.format == "txt"
        assert document.text == "hello world"
        assert document.pages[0].text == "hello world"
        assert document.metadata.word_count == 2


class TestReadMarkdown:
    MARKDOWN = (
        "# Title\n"
        "Intro paragraph.\n\n"
        "## Section One\n"
        "Some [link](https://example.com) text.\n\n"
        "## Section Two\n"
        "More content.\n"
    )

    def test_extracts_headings(self) -> None:
        document = readers.read_markdown(self.MARKDOWN)

        assert [h.text for h in document.headings] == ["Title", "Section One", "Section Two"]
        assert document.headings[0].level == 1
        assert document.headings[1].level == 2

    def test_extracts_links(self) -> None:
        document = readers.read_markdown(self.MARKDOWN)

        assert len(document.links) == 1
        assert document.links[0].text == "link"
        assert document.links[0].url == "https://example.com"

    def test_builds_sections_from_headings(self) -> None:
        document = readers.read_markdown(self.MARKDOWN)

        assert len(document.sections) == 3
        assert document.sections[0].heading.text == "Title"
        assert "Intro paragraph" in document.sections[0].text
        assert document.sections[1].heading.text == "Section One"
        assert "Some [link]" in document.sections[1].text


class TestReadCsv:
    def test_parses_header_and_rows(self) -> None:
        document = readers.read_csv("name,age\nAda,30\nGrace,85\n")

        assert document.tables[0].headers == ("name", "age")
        assert document.tables[0].rows == (("Ada", "30"), ("Grace", "85"))
        assert document.structured["rows"] == [
            {"name": "Ada", "age": "30"},
            {"name": "Grace", "age": "85"},
        ]


class TestReadJson:
    def test_parses_valid_json(self) -> None:
        document = readers.read_json('{"a": 1, "b": [1, 2, 3]}')

        assert document.structured == {"a": 1, "b": [1, 2, 3]}

    def test_invalid_json_raises_document_parse_error(self) -> None:
        try:
            readers.read_json("{not valid json")
            assert False, "expected DocumentParseError"
        except DocumentParseError:
            pass


class TestReadXml:
    def test_parses_nested_elements_to_dict(self) -> None:
        document = readers.read_xml(
            "<root><item>A</item><item>B</item><name>test</name></root>"
        )

        assert document.structured["root"]["item"] == ["A", "B"]
        assert document.structured["root"]["name"] == "test"
        assert "A" in document.text and "B" in document.text

    def test_invalid_xml_raises_document_parse_error(self) -> None:
        try:
            readers.read_xml("<root><unclosed>")
            assert False, "expected DocumentParseError"
        except DocumentParseError:
            pass


class TestReadHtmlStdlibFallback:
    HTML = (
        "<html><head><title>My Page</title></head><body>"
        "<h1>Welcome</h1><p>Hello <a href=\"https://example.com\">world</a>.</p>"
        "</body></html>"
    )

    def test_extracts_title_headings_and_links_without_bs4(self) -> None:
        document = readers._read_html_stdlib(self.HTML)

        assert document.metadata.title == "My Page"
        assert document.headings[0].text == "Welcome"
        assert document.links[0].url == "https://example.com"
        assert "Hello" in document.text and "world" in document.text
        assert "<h1>" not in document.text
