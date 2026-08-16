"""
Unit tests for StandardCodingAgent, using a fake Brain -- never a real
Provider.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse
from parika.core.brain.goal_result import GoalResult
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from parika.modules.coding_agent.agent import CodingTaskDescriptor
from parika.modules.coding_agent.exceptions import CodingPlanValidationError
from parika.modules.coding_agent.standard_agent import StandardCodingAgent


class _FakeBrain:
    def __init__(self, responses: list[BrainResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[BrainRequest] = []

    def handle(self, request: BrainRequest) -> BrainResponse:
        self.requests.append(request)
        return self._responses.pop(0)


def _chat_goal_result(goal_id: str, content: str) -> GoalResult:
    return GoalResult(
        goal_id=goal_id,
        task_id="task-1",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(
            outputs={
                "result": ChatResult(
                    message=ChatMessage(role="assistant", content=content)
                )
            }
        ),
    )


def _tool_goal_result(goal_id: str, result: dict) -> GoalResult:
    from parika.core.tool_manager.response import ToolResponse

    return GoalResult(
        goal_id=goal_id,
        task_id="task-2",
        status=TaskStatus.COMPLETED,
        response=TaskResponse(outputs={"result": ToolResponse(result=result)}),
    )


@pytest.fixture()
def capability_registry(logger, event_bus) -> CapabilityRegistry:
    registry = CapabilityRegistry(event_bus, logger)
    registry.register(
        CapabilityDefinition(
            id="coding.search",
            name="Coding Search",
            description="x",
            category=CapabilityCategory.TOOL,
        )
    )
    registry.register(
        CapabilityDefinition(
            id="coding.plan_change",
            name="Plan Change",
            description="x",
            category=CapabilityCategory.LLM,
        )
    )
    return registry


def _task(**overrides) -> CodingTaskDescriptor:
    defaults = dict(instruction="add a test", workspace_root=Path("/workspace"))
    defaults.update(overrides)
    return CodingTaskDescriptor(**defaults)


def test_execute_decomposes_validates_and_runs_plan(
    capability_registry: CapabilityRegistry,
) -> None:
    plan_json = '{"steps": [{"id": "step_0", "capability_id": "coding.search", "inputs": {"query": "x"}}]}'

    fake_brain = _FakeBrain(
        [
            BrainResponse(
                request_id="r1",
                plan_id="p1",
                results=(_chat_goal_result("g1", plan_json),),
            ),
            BrainResponse(
                request_id="r2",
                plan_id="p2",
                results=(_tool_goal_result("step_0", {"count": 3}),),
            ),
        ]
    )

    agent = StandardCodingAgent(brain=fake_brain, capability_registry=capability_registry)  # type: ignore[arg-type]
    result = agent.execute(_task())

    assert result.succeeded
    assert "1 step" in result.summary
    assert len(fake_brain.requests) == 2


def test_execute_forwards_execution_requirements_into_decomposition_goal(
    capability_registry: CapabilityRegistry,
) -> None:
    plan_json = '{"steps": [{"id": "step_0", "capability_id": "coding.search", "inputs": {"query": "x"}}]}'

    fake_brain = _FakeBrain(
        [
            BrainResponse(
                request_id="r1",
                plan_id="p1",
                results=(_chat_goal_result("g1", plan_json),),
            ),
            BrainResponse(
                request_id="r2",
                plan_id="p2",
                results=(_tool_goal_result("step_0", {"count": 3}),),
            ),
        ]
    )

    agent = StandardCodingAgent(brain=fake_brain, capability_registry=capability_registry)  # type: ignore[arg-type]
    execution_requirements = {"reasoning_level": "complex"}

    agent.execute(_task(metadata={"execution_requirements": execution_requirements}))

    decomposition_goal = fake_brain.requests[0].goals[0]
    assert (
        decomposition_goal.metadata["execution_requirements"]
        == execution_requirements
    )


def test_execute_leaves_decomposition_goal_metadata_empty_without_a_hint(
    capability_registry: CapabilityRegistry,
) -> None:
    plan_json = '{"steps": [{"id": "step_0", "capability_id": "coding.search", "inputs": {"query": "x"}}]}'

    fake_brain = _FakeBrain(
        [
            BrainResponse(
                request_id="r1",
                plan_id="p1",
                results=(_chat_goal_result("g1", plan_json),),
            ),
            BrainResponse(
                request_id="r2",
                plan_id="p2",
                results=(_tool_goal_result("step_0", {"count": 3}),),
            ),
        ]
    )

    agent = StandardCodingAgent(brain=fake_brain, capability_registry=capability_registry)  # type: ignore[arg-type]
    agent.execute(_task())

    decomposition_goal = fake_brain.requests[0].goals[0]
    assert decomposition_goal.metadata == {}


def test_execute_raises_on_disallowed_capability_in_plan(
    capability_registry: CapabilityRegistry,
) -> None:
    plan_json = '{"steps": [{"capability_id": "memory.remember"}]}'
    fake_brain = _FakeBrain(
        [
            BrainResponse(
                request_id="r1",
                plan_id="p1",
                results=(_chat_goal_result("g1", plan_json),),
            )
        ]
    )

    agent = StandardCodingAgent(brain=fake_brain, capability_registry=capability_registry)  # type: ignore[arg-type]

    with pytest.raises(CodingPlanValidationError):
        agent.execute(_task())


def test_execute_retries_once_on_malformed_plan_response(
    capability_registry: CapabilityRegistry,
) -> None:
    fake_brain = _FakeBrain(
        [
            BrainResponse(
                request_id="r1", plan_id="p1", results=(_chat_goal_result("g1", "not json"),)
            ),
            BrainResponse(
                request_id="r2",
                plan_id="p2",
                results=(
                    _chat_goal_result(
                        "g2", '{"steps": [{"capability_id": "coding.search"}]}'
                    ),
                ),
            ),
            BrainResponse(
                request_id="r3",
                plan_id="p3",
                results=(_tool_goal_result("step_0", {"count": 1}),),
            ),
        ]
    )

    agent = StandardCodingAgent(brain=fake_brain, capability_registry=capability_registry)  # type: ignore[arg-type]
    result = agent.execute(_task())

    assert result.succeeded
    assert len(fake_brain.requests) == 3
