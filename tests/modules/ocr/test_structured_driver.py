"""
Unit tests for OcrTableToolDriver/OcrFormToolDriver, using a fake
Brain (never a real Provider or a real filesystem).
Mirrors `test_ocr_tool_driver.py`'s own fake-Brain shape; table-region
detection is exercised against a real, small synthetic grid image
since that part of `OcrTableToolDriver` genuinely decodes pixels.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image, ImageDraw

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.modules.ocr.exceptions import OcrImageReadError
from parika.modules.ocr.module_driver import PROVIDER_EXTRACT_TEXT_CAPABILITY_ID
from parika.modules.ocr.structured_driver import OcrFormToolDriver, OcrTableToolDriver

_PLAIN_IMAGE_BASE64 = base64.b64encode(b"fake-image-bytes").decode("ascii")


def _grid_image_base64() -> str:
    image = Image.new("L", (400, 300), color=255)
    draw = ImageDraw.Draw(image)

    for y in range(20, 300, 60):
        draw.line([(20, y), (380, y)], fill=0, width=2)

    for x in range(20, 400, 90):
        draw.line([(x, 20), (x, 260)], fill=0, width=2)

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


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


def _brain_for(image_base64: str, recognized_text: str) -> _FakeBrain:
    return _FakeBrain(
        [
            BrainResponse(
                request_id="r1",
                plan_id="p1",
                results=(
                    _filesystem_read_result({"content_base64": image_base64}),
                ),
            ),
            BrainResponse(
                request_id="r2",
                plan_id="p2",
                results=(_recognition_result(recognized_text),),
            ),
        ]
    )


def _request(**arguments: object) -> ToolRequest:
    return ToolRequest(arguments=arguments)


class TestOcrTableToolDriver:
    def test_detects_grid_and_parses_json_response(self) -> None:
        fake_brain = _brain_for(
            _grid_image_base64(), '{"headers": ["A", "B"], "rows": [["1", "2"]]}'
        )
        driver = OcrTableToolDriver(
            brain=fake_brain, recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        response = driver.execute(_request(path="/mnt/dev/test/table.png"))

        assert response.result["table_detected"] is True
        assert len(response.result["regions"]) == 1
        assert response.result["parsed"] is True
        assert response.result["data"] == {"headers": ["A", "B"], "rows": [["1", "2"]]}
        assert len(fake_brain.requests) == 2

    def test_no_grid_reports_table_not_detected_but_still_extracts(self) -> None:
        fake_brain = _brain_for(_PLAIN_IMAGE_BASE64, '{"rows": []}')
        driver = OcrTableToolDriver(
            brain=fake_brain, recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        response = driver.execute(_request(path="/mnt/dev/test/notable.png"))

        assert response.result["table_detected"] is False
        assert response.result["regions"] == []
        assert response.result["parsed"] is True

    def test_unparseable_model_response_reports_parsed_false(self) -> None:
        fake_brain = _brain_for(_PLAIN_IMAGE_BASE64, "I could not read a table here.")
        driver = OcrTableToolDriver(
            brain=fake_brain, recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        response = driver.execute(_request(path="/mnt/dev/test/notable.png"))

        assert response.result["parsed"] is False
        assert response.result["data"] is None
        assert response.result["raw_text"] == "I could not read a table here."

    def test_raises_when_path_is_missing(self) -> None:
        driver = OcrTableToolDriver(
            brain=_FakeBrain([]), recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        with pytest.raises(OcrImageReadError):
            driver.execute(_request())


class TestOcrFormToolDriver:
    def test_extracts_key_value_pairs(self) -> None:
        fake_brain = _brain_for(_PLAIN_IMAGE_BASE64, '{"Name": "Ada", "Age": "30"}')
        driver = OcrFormToolDriver(
            brain=fake_brain, recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        response = driver.execute(_request(path="/mnt/dev/test/form.png"))

        assert response.result["parsed"] is True
        assert response.result["data"] == {"Name": "Ada", "Age": "30"}
        assert len(fake_brain.requests) == 2

    def test_additional_instruction_is_appended(self) -> None:
        fake_brain = _brain_for(_PLAIN_IMAGE_BASE64, "{}")
        driver = OcrFormToolDriver(
            brain=fake_brain, recognize_capability_id=PROVIDER_EXTRACT_TEXT_CAPABILITY_ID  # type: ignore[arg-type]
        )

        driver.execute(
            _request(
                path="/mnt/dev/test/form.png",
                instruction="Pay special attention to the signature box.",
            )
        )

        recognize_goal = fake_brain.requests[1].goals[0]
        built_request = recognize_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert "signature box" in built_request.messages[0].content
