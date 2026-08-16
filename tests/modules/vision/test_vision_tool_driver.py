"""
Unit tests for VisionToolDriver, using a fake Brain -- never a real
Provider or a real filesystem. Mirrors
`tests/modules/ocr/test_ocr_tool_driver.py`'s own fake-Brain shape
exactly.
"""

from __future__ import annotations

import base64

import pytest

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.modules.vision.driver import (
    FILESYSTEM_READ_CAPABILITY_ID,
    VisionToolDriver,
)
from parika.modules.vision.exceptions import (
    VisionAnalysisError,
    VisionImageReadError,
)

_IMAGE_BASE64 = base64.b64encode(b"fake-image-bytes").decode("ascii")
_PROVIDER_CAPABILITY_ID = "vision.provider_describe_image"
_DEFAULT_INSTRUCTION = "Describe this image in detail."


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


def _failed_result(reason: str) -> GoalResult:
    return GoalResult(
        goal_id="g1",
        task_id="task-1",
        status=TaskStatus.FAILED,
        response=None,
        failure=RuntimeError(reason),
    )


def _analysis_result(text: str) -> GoalResult:
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


def _request(**arguments: object) -> ToolRequest:
    return ToolRequest(arguments=arguments)


def _driver(
    fake_brain: _FakeBrain,
    *,
    provider_capability_id: str = _PROVIDER_CAPABILITY_ID,
    default_instruction: str = _DEFAULT_INSTRUCTION,
    question_argument: bool = False,
) -> VisionToolDriver:
    return VisionToolDriver(
        brain=fake_brain,  # type: ignore[arg-type]
        provider_capability_id=provider_capability_id,
        default_instruction=default_instruction,
        question_argument=question_argument,
    )


class TestVisionToolDriverExecute:
    def test_reads_image_and_analyzes_it(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result(
                            {
                                "path": "/mnt/dev/test/photo.png",
                                "content_base64": _IMAGE_BASE64,
                                "encoding": "base64",
                                "size": 17,
                            }
                        ),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(
                        _analysis_result(
                            "A golden retriever sitting on a green lawn."
                        ),
                    ),
                ),
            ]
        )

        driver = _driver(fake_brain)

        response = driver.execute(
            _request(
                path="/mnt/dev/test/photo.png",
                instruction="Describe the animal in this photo",
            )
        )

        assert response.result == {
            "text": "A golden retriever sitting on a green lawn."
        }
        assert response.attributes["path"] == "/mnt/dev/test/photo.png"

        assert len(fake_brain.requests) == 2

        read_goal = fake_brain.requests[0].goals[0]
        assert read_goal.capability_id == FILESYSTEM_READ_CAPABILITY_ID
        assert read_goal.inputs == {
            "path": "/mnt/dev/test/photo.png",
            "binary": True,
        }
        assert read_goal.provider_request_builder is None

        analyze_goal = fake_brain.requests[1].goals[0]
        assert analyze_goal.capability_id == _PROVIDER_CAPABILITY_ID
        assert analyze_goal.provider_request_builder is not None

        # The provider_request_builder closure -- exactly like
        # OcrToolDriver's own -- is never invoked by the driver
        # itself; Planner invokes it once a model is selected.
        built_request = analyze_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert isinstance(built_request, ChatRequest)
        assert len(built_request.messages) == 1

        sent_message = built_request.messages[0]
        assert sent_message.role == "user"
        assert sent_message.content == "Describe the animal in this photo"
        assert sent_message.images == (_IMAGE_BASE64,)

    def test_uses_default_instruction_when_omitted(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _IMAGE_BASE64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_analysis_result("some description"),),
                ),
            ]
        )

        driver = _driver(fake_brain)

        driver.execute(_request(path="/mnt/dev/test/photo.png"))

        analyze_goal = fake_brain.requests[1].goals[0]
        built_request = analyze_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert built_request.messages[0].content == _DEFAULT_INSTRUCTION

    def test_raises_when_path_is_missing(self) -> None:
        driver = _driver(_FakeBrain([]))

        with pytest.raises(VisionImageReadError):
            driver.execute(_request())

    def test_raises_when_filesystem_read_fails(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(_failed_result("path not found"),),
                )
            ]
        )

        driver = _driver(fake_brain)

        with pytest.raises(VisionImageReadError, match="path not found"):
            driver.execute(_request(path="/mnt/dev/test/missing.png"))

    def test_raises_when_analysis_fails(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _IMAGE_BASE64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_failed_result("no Vision-capable model available"),),
                ),
            ]
        )

        driver = _driver(fake_brain)

        with pytest.raises(
            VisionAnalysisError, match="no Vision-capable model"
        ):
            driver.execute(_request(path="/mnt/dev/test/photo.png"))


class TestVisionToolDriverForwardsExecutionRequirements:
    """
    AI-assisted model-selection refinement: a routing model's
    `model_selection_hint` (extracted by `ToolCallResolver`, see
    `parika/providers/ollama/tool_calling.py`) arrives here as
    `ToolRequest.metadata["execution_requirements"]` and must be
    forwarded, unmodified, onto the inner Provider-backed Goal's own
    `metadata` -- the Model Selection Framework's existing filtering/
    scoring pipeline (entirely unmodified) is what actually acts on
    it.
    """

    def _responses(self) -> list[BrainResponse]:
        return [
            BrainResponse(
                request_id="r1",
                plan_id="p1",
                results=(
                    _filesystem_read_result({"content_base64": _IMAGE_BASE64}),
                ),
            ),
            BrainResponse(
                request_id="r2",
                plan_id="p2",
                results=(_analysis_result("some description"),),
            ),
        ]

    def test_forwards_hint_into_inner_goal_metadata(self) -> None:
        fake_brain = _FakeBrain(self._responses())
        driver = _driver(fake_brain)

        execution_requirements = {
            "reasoning_level": "simple",
            "metadata": {
                "candidate_models": [
                    {"provider_id": "provider.ollama", "model_id": "minicpm-v4.5"}
                ]
            },
        }

        driver.execute(
            ToolRequest(
                arguments={"path": "/mnt/dev/test/photo.png"},
                metadata={"execution_requirements": execution_requirements},
            )
        )

        analyze_goal = fake_brain.requests[1].goals[0]
        assert (
            analyze_goal.metadata["execution_requirements"]
            == execution_requirements
        )

    def test_no_hint_leaves_inner_goal_metadata_empty(self) -> None:
        fake_brain = _FakeBrain(self._responses())
        driver = _driver(fake_brain)

        driver.execute(_request(path="/mnt/dev/test/photo.png"))

        analyze_goal = fake_brain.requests[1].goals[0]
        assert analyze_goal.metadata == {}

    def test_read_goal_never_receives_execution_requirements(self) -> None:
        # Only the Provider-backed inner Goal (`analyze_goal`) is a
        # Model Selection Framework candidate; the filesystem.read
        # Goal is a TOOL-category Goal and must stay unaffected.
        fake_brain = _FakeBrain(self._responses())
        driver = _driver(fake_brain)

        driver.execute(
            ToolRequest(
                arguments={"path": "/mnt/dev/test/photo.png"},
                metadata={"execution_requirements": {"reasoning_level": "complex"}},
            )
        )

        read_goal = fake_brain.requests[0].goals[0]
        assert read_goal.metadata == {}


class TestVisionToolDriverQuestionArgument:
    """Covers `vision.answer_question`'s `question_argument=True` shape."""

    def test_uses_question_as_instruction(self) -> None:
        fake_brain = _FakeBrain(
            [
                BrainResponse(
                    request_id="r1",
                    plan_id="p1",
                    results=(
                        _filesystem_read_result({"content_base64": _IMAGE_BASE64}),
                    ),
                ),
                BrainResponse(
                    request_id="r2",
                    plan_id="p2",
                    results=(_analysis_result("A red sedan."),),
                ),
            ]
        )

        driver = _driver(
            fake_brain,
            provider_capability_id="vision.provider_answer_question",
            default_instruction="",
            question_argument=True,
        )

        response = driver.execute(
            _request(
                path="/mnt/dev/test/car.png",
                question="What color is the car?",
            )
        )

        assert response.result == {"text": "A red sedan."}

        analyze_goal = fake_brain.requests[1].goals[0]
        built_request = analyze_goal.provider_request_builder(None, None)  # type: ignore[arg-type]
        assert built_request.messages[0].content == "What color is the car?"

    def test_raises_when_question_is_missing(self) -> None:
        driver = _driver(
            _FakeBrain([]),
            provider_capability_id="vision.provider_answer_question",
            default_instruction="",
            question_argument=True,
        )

        with pytest.raises(VisionImageReadError, match="question"):
            driver.execute(_request(path="/mnt/dev/test/car.png"))

    def test_raises_when_question_is_blank(self) -> None:
        driver = _driver(
            _FakeBrain([]),
            provider_capability_id="vision.provider_answer_question",
            default_instruction="",
            question_argument=True,
        )

        with pytest.raises(VisionImageReadError, match="question"):
            driver.execute(
                _request(path="/mnt/dev/test/car.png", question="   ")
            )
