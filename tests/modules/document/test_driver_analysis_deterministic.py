from __future__ import annotations

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.modules.document.driver_analysis_deterministic import (
    DocumentDeterministicAnalysisToolDriver,
)
from parika.modules.document.exceptions import DocumentReadError

from .conftest import DispatchingFakeBrain, filesystem_text_result


def _request(**arguments: object) -> ToolRequest:
    return ToolRequest(arguments=arguments)


def _brain(text: str = "apple banana apple 2024-01-05 ada@example.com") -> DispatchingFakeBrain:
    return DispatchingFakeBrain({"filesystem.read": lambda goal: filesystem_text_result(text)})


class TestSearch:
    def test_finds_match_with_context(self) -> None:
        driver = DocumentDeterministicAnalysisToolDriver(brain=_brain(), kind="search")

        response = driver.execute(_request(path="/docs/a.txt", query="banana"))

        assert response.result["match_count"] == 1

    def test_missing_query_raises(self) -> None:
        driver = DocumentDeterministicAnalysisToolDriver(brain=_brain(), kind="search")

        with pytest.raises(DocumentReadError):
            driver.execute(_request(path="/docs/a.txt"))


class TestExtractKeywords:
    def test_returns_ranked_keywords(self) -> None:
        driver = DocumentDeterministicAnalysisToolDriver(
            brain=_brain(), kind="extract_keywords"
        )

        response = driver.execute(_request(path="/docs/a.txt"))

        assert response.result["keywords"][0]["keyword"] == "apple"


class TestExtractDates:
    def test_returns_dates_found(self) -> None:
        driver = DocumentDeterministicAnalysisToolDriver(brain=_brain(), kind="extract_dates")

        response = driver.execute(_request(path="/docs/a.txt"))

        assert "2024-01-05" in response.result["dates"]


class TestExtractContacts:
    def test_returns_emails_found(self) -> None:
        driver = DocumentDeterministicAnalysisToolDriver(
            brain=_brain(), kind="extract_contacts"
        )

        response = driver.execute(_request(path="/docs/a.txt"))

        assert "ada@example.com" in response.result["emails"]


class TestDetectLanguage:
    def test_returns_detection_result_shape(self) -> None:
        driver = DocumentDeterministicAnalysisToolDriver(
            brain=_brain("This is clearly written in the English language today."),
            kind="detect_language",
        )

        response = driver.execute(_request(path="/docs/a.txt"))

        assert "detected" in response.result
        assert "candidates" in response.result


class TestDetectDuplicates:
    def test_requires_other_path(self) -> None:
        driver = DocumentDeterministicAnalysisToolDriver(
            brain=_brain(), kind="detect_duplicates"
        )

        with pytest.raises(DocumentReadError):
            driver.execute(_request(path="/docs/a.txt"))

    def test_identical_documents_are_identical(self) -> None:
        brain = DispatchingFakeBrain(
            {"filesystem.read": lambda goal: filesystem_text_result("same content")}
        )
        driver = DocumentDeterministicAnalysisToolDriver(
            brain=brain, kind="detect_duplicates"
        )

        response = driver.execute(_request(path="/docs/a.txt", other_path="/docs/b.txt"))

        assert response.result["identical"] is True
        assert response.result["similarity"] == 1.0
