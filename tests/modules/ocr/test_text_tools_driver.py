"""
Unit tests for OcrLayoutToolDriver/OcrLanguageToolDriver, using a fake
Brain. Both drivers accept either an already-known `text` (zero Brain
calls at all) or a `path` fallback (exactly the same two-Goal shape
`OcrToolDriver` uses) - both paths are exercised here.
"""

from __future__ import annotations

import pytest

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.modules.ocr.config import OcrToolConfig
from parika.modules.ocr.exceptions import (
    OcrDependencyUnavailableError,
    OcrImageReadError,
)
from parika.modules.ocr.module_driver import PROVIDER_EXTRACT_TEXT_CAPABILITY_ID
from parika.modules.ocr.text_tools_driver import (
    OcrLanguageToolDriver,
    OcrLayoutToolDriver,
)

_SAMPLE_TEXT = (
    "INTRODUCTION\n"
    "\n"
    "This is the first paragraph of the introduction, explaining the "
    "purpose of this document in reasonable detail.\n"
    "\n"
    "DETAILS\n"
    "\n"
    "Here are more details about the topic at hand, spread across a "
    "second, longer paragraph of body text."
)


class _FakeBrain:
    def __init__(self, responses: list[BrainResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[BrainRequest] = []

    def handle(self, request: BrainRequest) -> BrainResponse:
        self.requests.append(request)
        return self._responses.pop(0)


def _filesystem_read_result(payload: dict) -> GoalResult:
    return GoalResult(
        goal_id="g1",
        task_id="task-1",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(outputs={"result": ToolResponse(result=payload)}),
    )


def _recognition_result(text: str) -> GoalResult:
    return GoalResult(
        goal_id="g2",
        task_id="task-2",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(
            outputs={
                "result": ChatResult(
                    message=ChatMessage(role="assistant", content=text)
                )
            }
        ),
    )


def _path_fallback_brain(text: str) -> _FakeBrain:
    return _FakeBrain(
        [
            BrainResponse(
                request_id="r1",
                plan_id="p1",
                results=(_filesystem_read_result({"content_base64": "Zm9v"}),),
            ),
            BrainResponse(
                request_id="r2", plan_id="p2", results=(_recognition_result(text),)
            ),
        ]
    )


def _request(**arguments: object) -> ToolRequest:
    return ToolRequest(arguments=arguments)


class TestOcrLayoutToolDriver:
    def test_text_argument_never_calls_brain(self) -> None:
        fake_brain = _FakeBrain([])
        driver = OcrLayoutToolDriver(
            brain=fake_brain, recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        response = driver.execute(_request(text=_SAMPLE_TEXT))

        assert response.result["text"] == _SAMPLE_TEXT
        # Each heading sits in its own blank-line-isolated group, distinct
        # from the (also blank-line-separated) paragraph that follows it -
        # see `text_layout.py`'s own documented scope for this heuristic.
        assert response.result["paragraphs"] == [
            "INTRODUCTION",
            "This is the first paragraph of the introduction, explaining "
            "the purpose of this document in reasonable detail.",
            "DETAILS",
            "Here are more details about the topic at hand, spread across "
            "a second, longer paragraph of body text.",
        ]
        assert response.result["headings"] == ["INTRODUCTION", "DETAILS"]
        assert response.result["reading_order"] == "top_to_bottom"
        assert response.result["character_count"] == len(_SAMPLE_TEXT)
        assert len(fake_brain.requests) == 0

    def test_path_fallback_performs_read_and_recognize(self) -> None:
        fake_brain = _path_fallback_brain("Line one.\nLine two.")
        driver = OcrLayoutToolDriver(
            brain=fake_brain, recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        response = driver.execute(_request(path="/mnt/dev/test/p1.png"))

        assert response.result["lines"] == ["Line one.", "Line two."]
        assert len(fake_brain.requests) == 2

    def test_raises_when_neither_text_nor_path_given(self) -> None:
        driver = OcrLayoutToolDriver(
            brain=_FakeBrain([]), recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        with pytest.raises(OcrImageReadError):
            driver.execute(_request())


class TestOcrLanguageToolDriver:
    def test_text_argument_never_calls_brain(self) -> None:
        fake_brain = _FakeBrain([])
        driver = OcrLanguageToolDriver(
            brain=fake_brain, recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        response = driver.execute(
            _request(text="This is an ordinary English sentence for testing.")
        )

        assert response.result["detected"]
        assert response.result["language"] == "en"
        assert len(fake_brain.requests) == 0

    def test_path_fallback_performs_read_and_recognize(self) -> None:
        fake_brain = _path_fallback_brain(
            "This is an ordinary English sentence for testing."
        )
        driver = OcrLanguageToolDriver(
            brain=fake_brain, recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        response = driver.execute(_request(path="/mnt/dev/test/p1.png"))

        assert response.result["language"] == "en"
        assert len(fake_brain.requests) == 2

    def test_raises_dependency_unavailable_when_disabled_by_configuration(
        self,
    ) -> None:
        config = OcrToolConfig(language_detection_enabled=False)
        fake_brain = _FakeBrain([])
        driver = OcrLanguageToolDriver(
            brain=fake_brain,  # type: ignore[arg-type]
            recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID,
            config=config,
        )

        with pytest.raises(OcrDependencyUnavailableError):
            driver.execute(_request(text="some already-known text"))

        # The dependency check runs before resolving any text at all.
        assert len(fake_brain.requests) == 0

    def test_raises_when_neither_text_nor_path_given(self) -> None:
        driver = OcrLanguageToolDriver(
            brain=_FakeBrain([]), recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        with pytest.raises(OcrImageReadError):
            driver.execute(_request())
