from __future__ import annotations

from parika.core.tool_manager.request import ToolRequest
from parika.modules.document.driver_extraction import DocumentExtractionToolDriver

from .conftest import DispatchingFakeBrain, filesystem_text_result


def _request(**arguments: object) -> ToolRequest:
    return ToolRequest(arguments=arguments)


def _brain(text: str) -> DispatchingFakeBrain:
    return DispatchingFakeBrain({"filesystem.read": lambda goal: filesystem_text_result(text)})


class TestExtractHeadings:
    def test_returns_headings_from_markdown(self) -> None:
        driver = DocumentExtractionToolDriver(brain=_brain("# Title\nBody"), facet="headings")

        response = driver.execute(_request(path="/docs/a.md"))

        assert response.result["headings"] == [{"level": 1, "text": "Title"}]


class TestExtractMetadata:
    def test_returns_format_and_counts(self) -> None:
        driver = DocumentExtractionToolDriver(brain=_brain("one two three"), facet="metadata")

        response = driver.execute(_request(path="/docs/a.txt"))

        assert response.result["format"] == "txt"
        assert response.result["word_count"] == 3


class TestExtractTables:
    def test_returns_tables_from_csv(self) -> None:
        driver = DocumentExtractionToolDriver(brain=_brain("a,b\n1,2\n"), facet="tables")

        response = driver.execute(_request(path="/docs/a.csv"))

        assert response.result["tables"][0]["headers"] == ["a", "b"]


class TestExtractReferences:
    def test_returns_reference_entries(self) -> None:
        text = "Body.\n\nReferences\n[1] Author. Title. 2020.\n"
        driver = DocumentExtractionToolDriver(brain=_brain(text), facet="references")

        response = driver.execute(_request(path="/docs/a.txt"))

        assert len(response.result["references"]) == 1


class TestExtractSections:
    def test_falls_back_to_single_section_when_no_headings(self) -> None:
        driver = DocumentExtractionToolDriver(brain=_brain("plain body text"), facet="sections")

        response = driver.execute(_request(path="/docs/a.txt"))

        assert response.result["sections"] == [{"heading": None, "text": "plain body text"}]


class TestExtractAttachments:
    def test_non_office_format_returns_empty_list(self) -> None:
        driver = DocumentExtractionToolDriver(brain=_brain("plain body text"), facet="attachments")

        response = driver.execute(_request(path="/docs/a.txt"))

        assert response.result["attachments"] == []
