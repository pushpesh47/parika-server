from __future__ import annotations

import base64
from typing import Callable

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.response import ToolResponse


class DispatchingFakeBrain:
    """
    A fake `Brain` that routes each nested Goal to a handler keyed by
    `capability_id`, mirroring the real `Brain.handle()` contract
    (one `GoalResult` per Goal) without any real Planner/Provider/
    Tool execution. Shared by every Document Module driver test that
    needs more than one distinct nested Goal (`filesystem.read`,
    `ocr.extract_text`, `document.provider_analyze_content`).
    """

    def __init__(self, handlers: dict[str, Callable[[object], GoalResult]]) -> None:
        self._handlers = handlers
        self.requests: list[BrainRequest] = []

    def handle(self, request: BrainRequest) -> BrainResponse:
        self.requests.append(request)
        goal = request.goals[0]
        handler = self._handlers[goal.capability_id]

        return BrainResponse(
            request_id="r", plan_id="p", results=(handler(goal),)
        )


def filesystem_text_result(content: str) -> GoalResult:
    return GoalResult(
        goal_id="g",
        task_id="t",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(
            outputs={"result": ToolResponse(result={"content": content})}
        ),
    )


def filesystem_binary_result(data: bytes) -> GoalResult:
    encoded = base64.b64encode(data).decode("ascii")
    return GoalResult(
        goal_id="g",
        task_id="t",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(
            outputs={"result": ToolResponse(result={"content_base64": encoded})}
        ),
    )


def ocr_extract_text_result(payload: dict) -> GoalResult:
    return GoalResult(
        goal_id="g",
        task_id="t",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(
            outputs={"result": ToolResponse(result=payload)}
        ),
    )


def analysis_result(text: str) -> GoalResult:
    return GoalResult(
        goal_id="g",
        task_id="t",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(
            outputs={
                "result": ChatResult(
                    message=ChatMessage(role="assistant", content=text)
                )
            }
        ),
    )


def failed_result(reason: str = "not available") -> GoalResult:
    return GoalResult(
        goal_id="g", task_id="t", status=TaskStatus.FAILED, failure=RuntimeError(reason)
    )
