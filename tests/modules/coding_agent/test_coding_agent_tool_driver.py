"""
Unit tests for CodingAgentToolDriver, using a fake CodingAgentRegistry
-- never a real Brain/Provider.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.modules.coding_agent.agent import CodingAgentResult, CodingTaskDescriptor
from parika.modules.coding_agent.driver import CodingAgentToolDriver
from parika.modules.coding_agent.exceptions import CodingAgentError, CodingPlanValidationError


class _FakeAgent:
    def __init__(self, agent_id: str = "standard", *, error: Exception | None = None) -> None:
        self._id = agent_id
        self._error = error
        self.received_task: CodingTaskDescriptor | None = None

    @property
    def id(self) -> str:
        return self._id

    def supports(self, task: CodingTaskDescriptor) -> bool:
        return True

    def execute(self, task: CodingTaskDescriptor) -> CodingAgentResult:
        self.received_task = task

        if self._error is not None:
            raise self._error

        return CodingAgentResult(summary="Executed 1 step(s): 1 succeeded, 0 failed, 0 skipped.")


class _FakeRegistry:
    def __init__(self, agent: _FakeAgent) -> None:
        self._agent = agent

    def get(self, agent_id: str) -> _FakeAgent:
        return self._agent

    def select(self, task: CodingTaskDescriptor) -> _FakeAgent:
        return self._agent


def test_execute_requires_instruction() -> None:
    driver = CodingAgentToolDriver(
        registry=_FakeRegistry(_FakeAgent()),  # type: ignore[arg-type]
        default_workspace=Path("/workspace"),
    )

    with pytest.raises(CodingAgentError):
        driver.execute(ToolRequest())


def test_execute_returns_validated_result() -> None:
    agent = _FakeAgent()
    driver = CodingAgentToolDriver(
        registry=_FakeRegistry(agent),  # type: ignore[arg-type]
        default_workspace=Path("/workspace"),
    )

    response = driver.execute(ToolRequest(arguments={"instruction": "add a test"}))

    assert response.result["validated"] is True
    assert response.result["succeeded"] is True
    assert response.attributes["agent_id"] == "standard"


def test_execute_returns_structured_rejection_on_validation_error() -> None:
    agent = _FakeAgent(error=CodingPlanValidationError("bad plan"))
    driver = CodingAgentToolDriver(
        registry=_FakeRegistry(agent),  # type: ignore[arg-type]
        default_workspace=Path("/workspace"),
    )

    response = driver.execute(ToolRequest(arguments={"instruction": "do something risky"}))

    assert response.result["validated"] is False
    assert "bad plan" in response.result["reason"]
    assert response.attributes["rejected"] is True


def test_execute_reads_depth_from_request_metadata() -> None:
    agent = _FakeAgent()
    driver = CodingAgentToolDriver(
        registry=_FakeRegistry(agent),  # type: ignore[arg-type]
        default_workspace=Path("/workspace"),
    )

    driver.execute(
        ToolRequest(
            arguments={"instruction": "nested call"},
            metadata={"coding_agent_depth": 2},
        )
    )

    assert agent.received_task is not None
    assert agent.received_task.depth == 2


def test_execute_forwards_execution_requirements_into_task_metadata() -> None:
    agent = _FakeAgent()
    driver = CodingAgentToolDriver(
        registry=_FakeRegistry(agent),  # type: ignore[arg-type]
        default_workspace=Path("/workspace"),
    )

    execution_requirements = {"reasoning_level": "complex"}

    driver.execute(
        ToolRequest(
            arguments={"instruction": "refactor the module"},
            metadata={"execution_requirements": execution_requirements},
        )
    )

    assert agent.received_task is not None
    assert (
        agent.received_task.metadata["execution_requirements"]
        == execution_requirements
    )


def test_execute_leaves_task_metadata_empty_without_a_hint() -> None:
    agent = _FakeAgent()
    driver = CodingAgentToolDriver(
        registry=_FakeRegistry(agent),  # type: ignore[arg-type]
        default_workspace=Path("/workspace"),
    )

    driver.execute(ToolRequest(arguments={"instruction": "add a test"}))

    assert agent.received_task is not None
    assert agent.received_task.metadata == {}


def test_execute_uses_default_workspace_when_omitted() -> None:
    agent = _FakeAgent()
    driver = CodingAgentToolDriver(
        registry=_FakeRegistry(agent),  # type: ignore[arg-type]
        default_workspace=Path("/default/workspace"),
    )

    driver.execute(ToolRequest(arguments={"instruction": "x"}))

    assert agent.received_task.workspace_root == Path("/default/workspace")


def test_execute_propagates_unexpected_errors() -> None:
    agent = _FakeAgent(error=RuntimeError("boom"))
    driver = CodingAgentToolDriver(
        registry=_FakeRegistry(agent),  # type: ignore[arg-type]
        default_workspace=Path("/workspace"),
    )

    with pytest.raises(RuntimeError):
        driver.execute(ToolRequest(arguments={"instruction": "x"}))
