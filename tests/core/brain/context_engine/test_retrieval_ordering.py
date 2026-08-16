"""
Unit tests for assemble_context(), using real MemoryManager and
KnowledgeManager instances (SQLite-backed via tmp_path) rather than
fakes, to exercise the actual score-ranked search paths this module
depends on.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from parika.core.brain.context_engine.budget import TokenBudget
from parika.core.brain.context_engine.retrieval_ordering import assemble_context
from parika.core.brain.context_engine.token_estimator import HeuristicTokenEstimator
from parika.core.event_bus.event_bus import EventBus
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.registry import KnowledgeEngineRegistry
from parika.core.knowledge_manager.search_result import SearchResult
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.core.knowledge_manager.source_status import KnowledgeSourceStatus
from parika.core.knowledge_manager.sqlite_storage import SqliteKnowledgeStorage
from parika.core.logger.logger import Logger
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_kind import MemoryKind
from parika.core.memory_manager.memory_manager import MemoryManager
from parika.core.memory_manager.memory_origin import MemoryOrigin
from parika.core.planner.goal import Goal


def _goal(*, message: str = "", session_id: str | None = None) -> Goal:
    return Goal(
        id="g1",
        capability_id="chat.respond",
        inputs={"message": message} if message else {},
        metadata={"session_id": session_id} if session_id else {},
    )


@pytest.fixture
def memory_manager(logger: Logger, event_bus: EventBus, tmp_path: Path) -> Iterator[MemoryManager]:
    manager = MemoryManager(logger=logger, event_bus=event_bus, database_path=tmp_path / "memory.db")
    manager.initialize()

    yield manager

    manager.shutdown()


class _StaticKnowledgeEngine:
    def __init__(self, results: tuple[SearchResult, ...]) -> None:
        self._results = results

    def supports(self, source: KnowledgeSource) -> bool:
        return True

    def index(self, source: KnowledgeSource) -> int:
        return 0

    def remove(self, source: KnowledgeSource) -> None:
        return None

    def search(self, sources, query) -> tuple[SearchResult, ...]:
        return self._results


def _knowledge_manager_with_result(
    logger: Logger, event_bus: EventBus, tmp_path: Path, *, result: SearchResult
) -> KnowledgeManager:
    storage = SqliteKnowledgeStorage(tmp_path / "knowledge.db")
    storage.initialize()

    registry = KnowledgeEngineRegistry()
    registry.register(_StaticKnowledgeEngine((result,)))

    manager = KnowledgeManager(storage=storage, registry=registry, event_bus=event_bus, logger=logger)

    source = KnowledgeSource(
        id=uuid4(), name="s", kind=KnowledgeSourceKind.DOCUMENTATION,
        location="x", status=KnowledgeSourceStatus.AVAILABLE,
    )
    manager.register_source(source)

    return manager


class TestAssembleContext:
    def test_returns_empty_bundle_when_no_managers(self) -> None:
        bundle = assemble_context(
            goal=_goal(),
            memory_manager=None,
            knowledge_manager=None,
            budget=TokenBudget(),
            estimator=HeuristicTokenEstimator(),
        )

        assert bundle.memories == ()
        assert bundle.knowledge == ()
        assert bundle.estimated_tokens == 0

    def test_includes_relevant_memories(
        self, memory_manager: MemoryManager, logger: Logger
    ) -> None:
        memory_manager.register(
            Memory(
                memory_id="m1", kind=MemoryKind.PREFERENCE, origin=MemoryOrigin.USER_EXPLICIT,
                content="The user prefers dark mode.",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

        bundle = assemble_context(
            goal=_goal(message="dark mode"),
            memory_manager=memory_manager,
            knowledge_manager=None,
            budget=TokenBudget(),
            estimator=HeuristicTokenEstimator(),
        )

        assert len(bundle.memories) == 1
        assert bundle.estimated_tokens > 0

    def test_skips_knowledge_when_no_message(
        self, memory_manager: MemoryManager, event_bus: EventBus, logger: Logger, tmp_path: Path
    ) -> None:
        from parika.core.knowledge_manager.knowledge import Knowledge

        result = SearchResult(
            knowledge=Knowledge(
                id=uuid4(), source_id=uuid4(), title="t", content="c", location="l",
            ),
            score=1.0,
        )
        knowledge_manager = _knowledge_manager_with_result(
            logger, event_bus, tmp_path, result=result
        )

        bundle = assemble_context(
            goal=_goal(),  # no message
            memory_manager=memory_manager,
            knowledge_manager=knowledge_manager,
            budget=TokenBudget(),
            estimator=HeuristicTokenEstimator(),
        )

        assert bundle.knowledge == ()

    def test_includes_knowledge_when_message_present(
        self, memory_manager: MemoryManager, event_bus: EventBus, logger: Logger, tmp_path: Path
    ) -> None:
        from parika.core.knowledge_manager.knowledge import Knowledge

        result = SearchResult(
            knowledge=Knowledge(
                id=uuid4(), source_id=uuid4(), title="t", content="c", location="l",
            ),
            score=5.0,
        )
        knowledge_manager = _knowledge_manager_with_result(
            logger, event_bus, tmp_path, result=result
        )

        bundle = assemble_context(
            goal=_goal(message="tell me about c"),
            memory_manager=memory_manager,
            knowledge_manager=knowledge_manager,
            budget=TokenBudget(),
            estimator=HeuristicTokenEstimator(),
        )

        assert len(bundle.knowledge) == 1

    def test_respects_token_budget(self, memory_manager: MemoryManager) -> None:
        for i in range(5):
            memory_manager.register(
                Memory(
                    memory_id=f"m{i}", kind=MemoryKind.FACT, origin=MemoryOrigin.USER_EXPLICIT,
                    content="word " * 200,  # large content -> many estimated tokens
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    importance_score=float(i),
                )
            )

        tiny_budget = TokenBudget(max_context_tokens=50, reserved_for_response=0)

        bundle = assemble_context(
            goal=_goal(),
            memory_manager=memory_manager,
            knowledge_manager=None,
            budget=tiny_budget,
            estimator=HeuristicTokenEstimator(),
        )

        assert bundle.estimated_tokens <= tiny_budget.usable_tokens

    def test_no_fixed_entry_count_caps_inclusion_when_budget_is_generous(
        self, memory_manager: MemoryManager
    ) -> None:
        # Phase A.5: TokenBudget no longer has a max_memories field --
        # a generous token budget must include every relevant memory
        # that fits, never a fixed entry count independent of budget.
        for i in range(10):
            memory_manager.register(
                Memory(
                    memory_id=f"m{i}", kind=MemoryKind.FACT, origin=MemoryOrigin.USER_EXPLICIT,
                    content=f"distinct short fact number {i}",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    importance_score=float(i),
                )
            )

        generous_budget = TokenBudget(max_context_tokens=100000)

        bundle = assemble_context(
            goal=_goal(),
            memory_manager=memory_manager,
            knowledge_manager=None,
            budget=generous_budget,
            estimator=HeuristicTokenEstimator(),
        )

        assert len(bundle.memories) == 10

    def test_search_fetch_pool_scales_with_the_token_budget(
        self, memory_manager: MemoryManager
    ) -> None:
        # A larger Runtime Context Budget fetches a larger candidate
        # pool (never a hardcoded fetch count), so more of the
        # available memories become visible to the packer.
        for i in range(30):
            memory_manager.register(
                Memory(
                    memory_id=f"m{i}", kind=MemoryKind.FACT, origin=MemoryOrigin.USER_EXPLICIT,
                    content=f"distinct short fact number {i}",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    importance_score=float(i),
                )
            )

        tiny_budget = TokenBudget(max_context_tokens=5, reserved_for_response=0, safety_reserve_tokens=0)
        generous_budget = TokenBudget(max_context_tokens=100000)

        tiny_bundle = assemble_context(
            goal=_goal(),
            memory_manager=memory_manager,
            knowledge_manager=None,
            budget=tiny_budget,
            estimator=HeuristicTokenEstimator(),
        )
        generous_bundle = assemble_context(
            goal=_goal(),
            memory_manager=memory_manager,
            knowledge_manager=None,
            budget=generous_budget,
            estimator=HeuristicTokenEstimator(),
        )

        assert len(generous_bundle.memories) == 30
        assert len(tiny_bundle.memories) < len(generous_bundle.memories)

    def test_reports_conversation_message_count(
        self, memory_manager: MemoryManager
    ) -> None:
        bundle = assemble_context(
            goal=_goal(),
            memory_manager=memory_manager,
            knowledge_manager=None,
            budget=TokenBudget(),
            estimator=HeuristicTokenEstimator(),
            conversation_message_count=7,
        )

        assert bundle.conversation_message_count == 7

    def test_experience_success_rate_reported_when_source_supplied(
        self, memory_manager: MemoryManager
    ) -> None:
        class _FakeExperienceSource:
            def aggregate_outcome_rate(
                self, *, capability_id: str, provider_id=None, model_id=None
            ) -> float | None:
                return 0.75

        bundle = assemble_context(
            goal=_goal(),
            memory_manager=memory_manager,
            knowledge_manager=None,
            budget=TokenBudget(),
            estimator=HeuristicTokenEstimator(),
            experience_source=_FakeExperienceSource(),
        )

        assert bundle.experience_success_rate == 0.75

    def test_experience_success_rate_none_without_source(
        self, memory_manager: MemoryManager
    ) -> None:
        bundle = assemble_context(
            goal=_goal(),
            memory_manager=memory_manager,
            knowledge_manager=None,
            budget=TokenBudget(),
            estimator=HeuristicTokenEstimator(),
        )

        assert bundle.experience_success_rate is None

    def test_experience_source_exception_degrades_gracefully(
        self, memory_manager: MemoryManager
    ) -> None:
        class _RaisingExperienceSource:
            def aggregate_outcome_rate(
                self, *, capability_id: str, provider_id=None, model_id=None
            ) -> float | None:
                raise RuntimeError("backend unavailable")

        bundle = assemble_context(
            goal=_goal(),
            memory_manager=memory_manager,
            knowledge_manager=None,
            budget=TokenBudget(),
            estimator=HeuristicTokenEstimator(),
            experience_source=_RaisingExperienceSource(),
        )

        assert bundle.experience_success_rate is None

    def test_debug_logging_emits_context_assembly_stages(
        self, memory_manager: MemoryManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        logger = logging.getLogger("test.context_assembly")

        with caplog.at_level(logging.DEBUG, logger="test.context_assembly"):
            assemble_context(
                goal=_goal(),
                memory_manager=memory_manager,
                knowledge_manager=None,
                budget=TokenBudget(),
                estimator=HeuristicTokenEstimator(),
                logger=logger,
            )

        messages = "\n".join(record.message for record in caplog.records)
        assert "searching conversation history" in messages.lower()
        assert "searching permanent memory" in messages.lower()
        assert "searching knowledge" in messages.lower()
        assert "searching experience" in messages.lower()
        assert "context assembled" in messages.lower()
