"""
Unit tests for Brain's opt-in Context Engineering methods
(`assemble_context()`, `compact()`).

Uses minimal stand-ins for `planner`/`task_manager` since neither
method touches them -- this is a deliberately isolated test of the
context_engine integration, not a full pipeline test (that is already
covered by `test_brain.py`, which remains unmodified and passing).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from parika.core.brain.brain import Brain
from parika.core.brain.context_engine import ContextMessage, TokenBudget
from parika.core.brain.exceptions import ContextEngineUnavailableError
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_kind import MemoryKind
from parika.core.memory_manager.memory_manager import MemoryManager
from parika.core.memory_manager.memory_origin import MemoryOrigin
from parika.core.planner.goal import Goal


@pytest.fixture
def memory_manager(logger: Logger, event_bus: EventBus, tmp_path: Path) -> Iterator[MemoryManager]:
    manager = MemoryManager(logger=logger, event_bus=event_bus, database_path=tmp_path / "m.db")
    manager.initialize()

    yield manager

    manager.shutdown()


class TestAssembleContext:
    def test_raises_when_no_memory_manager(self, logger: Logger) -> None:
        brain = Brain(planner=None, task_manager=None, logger=logger)  # type: ignore[arg-type]

        with pytest.raises(ContextEngineUnavailableError):
            brain.assemble_context(
                Goal(id="g1", capability_id="chat.respond", inputs={})
            )

    def test_assembles_context_when_memory_manager_supplied(
        self, logger: Logger, memory_manager: MemoryManager
    ) -> None:
        memory_manager.register(
            Memory(
                memory_id="m1", kind=MemoryKind.FACT, origin=MemoryOrigin.USER_EXPLICIT,
                content="widget rendering details",
                created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
            )
        )

        brain = Brain(
            planner=None, task_manager=None, logger=logger,  # type: ignore[arg-type]
            memory_manager=memory_manager,
        )

        bundle = brain.assemble_context(
            Goal(id="g1", capability_id="chat.respond", inputs={"message": "widget rendering"})
        )

        assert len(bundle.memories) == 1

    def test_handle_is_unaffected_by_new_constructor_params(self, logger: Logger) -> None:
        # Constructing Brain with the new optional params defaulted to
        # None must leave every existing attribute exactly as before.
        brain = Brain(planner=None, task_manager=None, logger=logger)  # type: ignore[arg-type]

        assert brain._memory_manager is None
        assert brain._knowledge_manager is None


class TestCompact:
    def test_compact_is_callable_without_memory_manager(self, logger: Logger) -> None:
        brain = Brain(planner=None, task_manager=None, logger=logger)  # type: ignore[arg-type]

        result = brain.compact(
            [ContextMessage(role="user", content="hello")],
            budget=TokenBudget(max_context_tokens=100, reserved_for_response=0, safety_reserve_tokens=0),
        )

        assert result.dropped_count == 0

    def test_compact_drops_middle_turns_beyond_the_token_budget(self, logger: Logger) -> None:
        brain = Brain(planner=None, task_manager=None, logger=logger)  # type: ignore[arg-type]

        # Each "tN" turn costs exactly 1 estimated token.
        messages = [ContextMessage(role="user", content=f"t{i}") for i in range(10)]

        result = brain.compact(
            messages,
            budget=TokenBudget(max_context_tokens=2, reserved_for_response=0, safety_reserve_tokens=0),
        )

        assert result.dropped_count == 8

    def test_uses_default_budget_when_none_supplied(self, logger: Logger) -> None:
        brain = Brain(planner=None, task_manager=None, logger=logger)  # type: ignore[arg-type]

        messages = [ContextMessage(role="user", content="hi")]

        result = brain.compact(messages)

        assert result.dropped_count == 0
