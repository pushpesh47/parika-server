"""
Shared fake-Brain test support and a real synthetic test-video fixture
for the Video Module's ToolDrivers. Mirrors
`tests/modules/vision/conftest.py`'s own per-capability-dispatch
`FakeBrain` shape.
"""

from __future__ import annotations

from pathlib import Path
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


class FakeBrain:
    """
    Dispatches queued `BrainResponse`s by the first Goal's
    `capability_id`. `filesystem_info_result()` (queued automatically
    by the `fake_brain` fixture below for the `video_path` fixture's
    own path) satisfies every driver's initial `filesystem.info`
    validation Goal.
    """

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
                f"FakeBrain: no queued response for capability '{capability_id}'."
            )

        return queue.pop(0)

    def goals_for(self, capability_id: str) -> list[Any]:
        return [
            goal
            for request in self.requests
            for goal in request.goals
            if goal.capability_id == capability_id
        ]


def filesystem_info_result(resolved_path: str) -> BrainResponse:
    return BrainResponse(
        request_id="r-info",
        plan_id="p-info",
        results=(
            GoalResult(
                goal_id="g-info",
                task_id="t-info",
                status=TaskStatus.COMPLETED,
                response=TaskResponse(
                    outputs={
                        "result": ToolResponse(
                            result={"path": resolved_path, "is_file": True, "size": 1}
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


def provider_text_result(text: str) -> BrainResponse:
    return BrainResponse(
        request_id="r-provider",
        plan_id="p-provider",
        results=(
            GoalResult(
                goal_id="g-provider",
                task_id="t-provider",
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


@pytest.fixture
def video_path(tmp_path: Path) -> str:
    """
    A small, real, deterministic synthetic video: 50 frames at 10fps
    (64x64), black for the first half and green for the second half,
    with a moving white square throughout -- enough real visual
    structure to exercise scene-change/motion/blur/black-frame
    detection meaningfully, without depending on a checked-in binary
    fixture file.
    """

    cv2 = pytest.importorskip("cv2")
    import numpy as np

    path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 64))

    for index in range(50):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        frame[:, :] = (0, 0, 0) if index < 25 else (0, 200, 0)
        x = (index * 2) % 50
        frame[10:20, x : x + 10] = (255, 255, 255)
        writer.write(frame)

    writer.release()
    return str(path)


@pytest.fixture
def fake_brain(video_path: str) -> FakeBrain:
    brain = FakeBrain()
    brain.queue("filesystem.info", filesystem_info_result(video_path))
    return brain
