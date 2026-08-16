from __future__ import annotations

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.modules.document.driver_analysis import DocumentAnalysisToolDriver
from parika.modules.document.exceptions import DocumentReadError

from .conftest import DispatchingFakeBrain, analysis_result, filesystem_text_result


def _request(**arguments: object) -> ToolRequest:
    return ToolRequest(arguments=arguments)


def _brain(text: str = "Document body text.") -> DispatchingFakeBrain:
    return DispatchingFakeBrain(
        {
            "filesystem.read": lambda goal: filesystem_text_result(text),
            "document.provider_analyze_content": lambda goal: analysis_result(
                "Model response."
            ),
        }
    )


class TestSummarize:
    def test_uses_default_instruction_and_returns_text(self) -> None:
        brain = _brain()
        driver = DocumentAnalysisToolDriver(
            brain=brain,
            provider_capability_id="document.provider_analyze_content",
            default_instruction="Summarize this document.",
        )

        response = driver.execute(_request(path="/docs/report.txt"))

        assert response.result["text"] == "Model response."

        analyze_goal = brain.requests[1].goals[0]
        built = analyze_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert "Summarize this document." in built.messages[0].content
        assert "Document body text." in built.messages[0].content


class TestAnswerQuestion:
    def test_requires_question_argument(self) -> None:
        driver = DocumentAnalysisToolDriver(
            brain=_brain(),
            provider_capability_id="document.provider_analyze_content",
            question_argument=True,
        )

        with pytest.raises(DocumentReadError):
            driver.execute(_request(path="/docs/report.txt"))

    def test_question_becomes_the_instruction(self) -> None:
        brain = _brain()
        driver = DocumentAnalysisToolDriver(
            brain=brain,
            provider_capability_id="document.provider_analyze_content",
            question_argument=True,
        )

        driver.execute(_request(path="/docs/report.txt", question="What is the total?"))

        analyze_goal = brain.requests[1].goals[0]
        built = analyze_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert "What is the total?" in built.messages[0].content


class TestTranslate:
    def test_requires_target_language(self) -> None:
        driver = DocumentAnalysisToolDriver(
            brain=_brain(),
            provider_capability_id="document.provider_analyze_content",
            target_language_argument=True,
        )

        with pytest.raises(DocumentReadError):
            driver.execute(_request(path="/docs/report.txt"))

    def test_target_language_builds_translation_instruction(self) -> None:
        brain = _brain()
        driver = DocumentAnalysisToolDriver(
            brain=brain,
            provider_capability_id="document.provider_analyze_content",
            target_language_argument=True,
        )

        driver.execute(_request(path="/docs/report.txt", target_language="French"))

        analyze_goal = brain.requests[1].goals[0]
        built = analyze_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert "French" in built.messages[0].content


class TestCompareDocuments:
    def test_requires_other_path(self) -> None:
        driver = DocumentAnalysisToolDriver(
            brain=_brain(),
            provider_capability_id="document.provider_analyze_content",
            second_document_argument=True,
        )

        with pytest.raises(DocumentReadError):
            driver.execute(_request(path="/docs/a.txt"))

    def test_sends_both_documents_content(self) -> None:
        brain = DispatchingFakeBrain(
            {
                "filesystem.read": lambda goal: filesystem_text_result(
                    "Content of " + goal.inputs["path"]
                ),
                "document.provider_analyze_content": lambda goal: analysis_result("ok"),
            }
        )
        driver = DocumentAnalysisToolDriver(
            brain=brain,
            provider_capability_id="document.provider_analyze_content",
            default_instruction="Compare these documents.",
            second_document_argument=True,
        )

        driver.execute(_request(path="/docs/a.txt", other_path="/docs/b.txt"))

        analyze_goal = brain.requests[-1].goals[0]
        built = analyze_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert "Content of /docs/a.txt" in built.messages[0].content
        assert "Content of /docs/b.txt" in built.messages[0].content
