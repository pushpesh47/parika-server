"""
Unit tests for assemble_context(), using real MemoryManager and
KnowledgeManager instances (PostgreSQL-backed) rather than
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
from parika.core.knowledge_manager.postgresql_storage import PostgreSQLKnowledgeStorage
from parika.core.logger.logger import Logger
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_kind import MemoryKind
from parika.core.memory_manager.memory_manager import MemoryManager
from parika.core.memory_manager.postgresql_storage import PostgreSQLMemoryStorage
from parika.core.planner.goal import Goal
from parika.core.database.pool import PoolManager
from tests.conftest_db import build_test_db_config


def _goal() -> Goal:
    """Build a minimal Goal for testing."""
    return Goal(
        id="g1",
        capability_id="chat.respond",
        provider_request_builder=lambda _: None,
        metadata={},
    )


@pytest.fixture(scope="session")
def _test_db_pool():
    """Initialize PostgreSQL test pool for the test session."""
    db_config = build_test_db_config()
    pool = PoolManager.initialize_sync_pool(db_config)
    yield pool
    PoolManager.shutdown_sync_pool()


@pytest.fixture
def memory_manager(logger: Logger, event_bus: EventBus, _test_db_pool) -> Iterator[MemoryManager]:
    storage = PostgreSQLMemoryStorage(_test_db_pool)
    storage.initialize()
    manager = MemoryManager(
        logger=logger,
        event_bus=event_bus,
        database_path=_test_db_pool,  # PostgreSQL pool
        configuration=None,
        storage=storage,
    )

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
    logger: Logger, event_bus: EventBus, _test_db_pool, *, result: SearchResult
) -> KnowledgeManager:
    storage = PostgreSQLKnowledgeStorage(_test_db_pool)
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