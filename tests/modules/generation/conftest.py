"""
Shared fake-Brain test support for the Generation Module's ToolDrivers,
mirroring `tests/modules/vision/conftest.py`'s own shape exactly.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.provider_manager.generation_result import (
    GeneratedArtifact,
    GenerationResult,
)
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.response import ToolResponse

IMAGE_BASE64 = base64.b64encode(b"fake-image-bytes-one").decode("ascii")
VIDEO_BASE64 = base64.b64encode(b"fake-video-bytes-one").decode("ascii")
ARTIFACT_BASE64 = base64.b64encode(b"fake-generated-artifact-bytes").decode("ascii")


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


def generation_result(
    *, content_base64: str = ARTIFACT_BASE64, mime_type: str = "image/png"
) -> BrainResponse:
    return BrainResponse(
        request_id="r-generate",
        plan_id="p-generate",
        results=(
            GoalResult(
                goal_id="g-generate",
                task_id="t-generate",
                status=TaskStatus.COMPLETED,
                response=TaskResponse(
                    outputs={
                        "result": GenerationResult(
                            artifacts=(
                                GeneratedArtifact(
                                    content_base64=content_base64,
                                    mime_type=mime_type,
                                ),
                            )
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
