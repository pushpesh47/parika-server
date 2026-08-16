from __future__ import annotations

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.modules.document.driver_reading import DocumentReadingToolDriver
from parika.modules.document.exceptions import DocumentFormatError, DocumentReadError

from .conftest import (
    DispatchingFakeBrain,
    filesystem_binary_result,
    filesystem_text_result,
    ocr_extract_text_result,
)


def _request(**arguments: object) -> ToolRequest:
    return ToolRequest(arguments=arguments)


class TestExtractTextAutoDetect:
    def test_reads_markdown_by_extension(self) -> None:
        brain = DispatchingFakeBrain(
            {"filesystem.read": lambda goal: filesystem_text_result("# Title\nBody")}
        )
        driver = DocumentReadingToolDriver(brain=brain, expected_format=None)

        response = driver.execute(_request(path="/docs/readme.md"))

        assert response.result["format"] == "markdown"
        assert response.result["headings"][0]["text"] == "Title"

    def test_delegates_pdf_to_ocr_extract_text(self) -> None:
        brain = DispatchingFakeBrain(
            {
                "ocr.extract_text": lambda goal: ocr_extract_text_result(
                    {
                        "text": "page one\npage two",
                        "pages": [
                            {"page": 1, "text": "page one", "source": "text_layer"},
                            {"page": 2, "text": "page two", "source": "ocr"},
                        ],
                    }
                )
            }
        )
        driver = DocumentReadingToolDriver(brain=brain, expected_format=None)

        response = driver.execute(_request(path="/docs/report.pdf"))

        assert response.result["format"] == "pdf"
        assert response.result["pages"][0]["source"] == "native"
        assert response.result["pages"][1]["source"] == "ocr"
        assert response.result["metadata"]["page_count"] == 2

    def test_unknown_extension_raises_document_format_error(self) -> None:
        driver = DocumentReadingToolDriver(brain=DispatchingFakeBrain({}), expected_format=None)

        with pytest.raises(DocumentFormatError):
            driver.execute(_request(path="/docs/image.png"))

    def test_missing_path_raises(self) -> None:
        driver = DocumentReadingToolDriver(brain=DispatchingFakeBrain({}), expected_format=None)

        with pytest.raises(DocumentReadError):
            driver.execute(_request())


class TestReadFixedFormat:
    def test_read_csv_returns_table(self) -> None:
        brain = DispatchingFakeBrain(
            {"filesystem.read": lambda goal: filesystem_text_result("a,b\n1,2\n")}
        )
        driver = DocumentReadingToolDriver(brain=brain, expected_format="csv")

        response = driver.execute(_request(path="/docs/data.csv"))

        assert response.result["format"] == "csv"
        assert response.result["tables"][0]["headers"] == ["a", "b"]

    def test_read_txt_uses_binary_false_read(self) -> None:
        brain = DispatchingFakeBrain(
            {"filesystem.read": lambda goal: filesystem_text_result("hello")}
        )
        driver = DocumentReadingToolDriver(brain=brain, expected_format="txt")

        response = driver.execute(_request(path="/docs/notes.txt"))

        assert response.result["text"] == "hello"
        read_goal = brain.requests[0].goals[0]
        assert read_goal.inputs["binary"] is False
