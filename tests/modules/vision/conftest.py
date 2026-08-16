"""
Shared fake-Brain test support for the Vision Module's new
deterministic-first ToolDrivers (`driver_compare.py`,
`driver_counting.py`, `driver_detection.py`, `driver_quality.py`,
`driver_collection.py`, `driver_editing.py`).

Unlike `test_vision_tool_driver.py`'s own strictly ordered
`_FakeBrain` (each `VisionToolDriver` issues exactly two Goals in a
fixed order), these new drivers issue a variable number of Goals
across `filesystem.read`/`filesystem.write`/`filesystem.list` and
their own `vision.provider_*` Capability, so `FakeBrain` here
dispatches by `Goal.capability_id` instead -- a per-capability queue,
popped in call order for that specific capability only.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.response import ToolResponse

IMAGE_BASE64 = base64.b64encode(b"fake-image-bytes-one").decode("ascii")
IMAGE_B_BASE64 = base64.b64encode(b"fake-image-bytes-two").decode("ascii")


class FakeBrain:
    """Dispatches queued `BrainResponse`s by the first Goal's `capability_id`."""

    def __init__(self) -> None:
        self.requests: list[BrainRequest] = []
        self._queues: dict[str, list[BrainResponse]] = {}

    def queue(self, capability_id: str, response: BrainResponse) -> None:
        self._queues.setdefault(capability_id, []).append(response)

    def handle(self, request: BrainRequest) -> BrainResponse:
        self.requests.append(request)
        capability_id = request.goals[0].capability_id
        queue = self._queues.get(capability_id)

        if not queue:
            raise AssertionError(
                f"FakeBrain: no queued response for capability "
                f"'{capability_id}'."
            )

        return queue.pop(0)

    def goals_for(self, capability_id: str) -> list[Any]:
        return [
            goal
            for request in self.requests
            for goal in request.goals
            if goal.capability_id == capability_id
        ]


def read_result(payload: dict | None = None) -> BrainResponse:
    body = {"content_base64": IMAGE_BASE64, "size": 123}
    if payload:
        body.update(payload)

    return BrainResponse(
        request_id="r-read",
        plan_id="p-read",
        results=(
            GoalResult(
                goal_id="g-read",
                task_id="t-read",
                status=TaskStatus.COMPLETED,
                response=TaskResponse(outputs={"result": ToolResponse(result=body)}),
            ),
        ),
    )


def write_result(path: str = "/tmp/out.png") -> BrainResponse:
    return BrainResponse(
        request_id="r-write",
        plan_id="p-write",
        results=(
            GoalResult(
                goal_id="g-write",
                task_id="t-write",
                status=TaskStatus.COMPLETED,
                response=TaskResponse(
                    outputs={
                        "result": ToolResponse(
                            result={"path": path, "bytes_written": 10, "mode": "overwrite"}
                        )
                    }
                ),
            ),
        ),
    )


def list_result(entries: list[dict]) -> BrainResponse:
    return BrainResponse(
        request_id="r-list",
        plan_id="p-list",
        results=(
            GoalResult(
                goal_id="g-list",
                task_id="t-list",
                status=TaskStatus.COMPLETED,
                response=TaskResponse(
                    outputs={
                        "result": ToolResponse(
                            result={"path": "/dir", "pattern": None, "entries": entries}
                        )
                    }
                ),
            ),
        ),
    )


def analysis_result(text: str) -> BrainResponse:
    return BrainResponse(
        request_id="r-analyze",
        plan_id="p-analyze",
        results=(
            GoalResult(
                goal_id="g-analyze",
                task_id="t-analyze",
                status=TaskStatus.COMPLETED,
                response=TaskResponse(
                    outputs={
                        "result": ChatResult(
                            message=ChatMessage(role="assistant", content=text)
                        )
                    }
                ),
            ),
        ),
    )


def failed_result(reason: str) -> BrainResponse:
    return BrainResponse(
        request_id="r-failed",
        plan_id="p-failed",
        results=(
            GoalResult(
                goal_id="g-failed",
                task_id="t-failed",
                status=TaskStatus.FAILED,
                response=None,
                failure=RuntimeError(reason),
            ),
        ),
    )


@pytest.fixture
def fake_brain() -> FakeBrain:
    return FakeBrain()
