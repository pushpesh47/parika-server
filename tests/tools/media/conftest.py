"""
Shared fake-Brain test support for the Media Tool's `MediaResolver`,
mirroring `tests/modules/voice/conftest.py`'s own shape exactly - a
`FakeBrain` that queues `BrainResponse`s by the first Goal's
`capability_id`, used here to fake the `web.search` Capability's
nested-Goal result without a real network call.
"""

from __future__ import annotations

from typing import Any

import pytest

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.response import ToolResponse


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
                f"FakeBrain: no queued response for capability '{capability_id}'."
            )

        return queue.pop(0)


def web_search_result(results: tuple[dict[str, Any], ...]) -> BrainResponse:
    return BrainResponse(
        request_id="r-search",
        plan_id="p-search",
        results=(
            GoalResult(
                goal_id="g-search",
                task_id="t-search",
                status=TaskStatus.COMPLETED,
                response=TaskResponse(outputs={"result": ToolResponse(result=results)}),
            ),
        ),
    )


@pytest.fixture
def fake_brain() -> FakeBrain:
    return FakeBrain()
