"""
Unit tests for CodingAgentRegistry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.modules.coding_agent.agent import CodingTaskDescriptor
from parika.modules.coding_agent.exceptions import UnknownCodingAgentError
from parika.modules.coding_agent.registry import CodingAgentRegistry


class _FakeAgent:
    def __init__(self, agent_id: str, *, supports_result: bool = False) -> None:
        self._id = agent_id
        self._supports_result = supports_result

    @property
    def id(self) -> str:
        return self._id

    def supports(self, task: CodingTaskDescriptor) -> bool:
        return self._supports_result

    def execute(self, task: CodingTaskDescriptor):
        raise NotImplementedError


def _task() -> CodingTaskDescriptor:
    return CodingTaskDescriptor(instruction="x", workspace_root=Path("/workspace"))


def test_select_falls_back_to_last_agent_when_none_support() -> None:
    fast = _FakeAgent("fast", supports_result=False)
    standard = _FakeAgent("standard", supports_result=False)
    registry = CodingAgentRegistry((fast, standard))

    assert registry.select(_task()).id == "standard"


def test_select_prefers_first_matching_agent() -> None:
    security = _FakeAgent("security_review", supports_result=True)
    standard = _FakeAgent("standard", supports_result=True)
    registry = CodingAgentRegistry((security, standard))

    assert registry.select(_task()).id == "security_review"


def test_explicit_requested_agent_id_bypasses_heuristic() -> None:
    fast = _FakeAgent("fast", supports_result=False)
    standard = _FakeAgent("standard", supports_result=True)
    registry = CodingAgentRegistry((fast, standard))

    task = CodingTaskDescriptor(
        instruction="x", workspace_root=Path("/workspace"), requested_agent_id="fast"
    )
    assert registry.select(task).id == "fast"


def test_get_raises_for_unknown_agent_id() -> None:
    registry = CodingAgentRegistry((_FakeAgent("standard", supports_result=True),))

    with pytest.raises(UnknownCodingAgentError):
        registry.get("nonexistent")


def test_registry_requires_at_least_one_agent() -> None:
    with pytest.raises(ValueError):
        CodingAgentRegistry(())
