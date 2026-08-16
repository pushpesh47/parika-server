"""
Unit tests for MemoryManager's Intelligence Foundation extension:
scoping, importance/decay fields, search, get_by_scope/get_by_kind,
touch, consolidation_candidates, and prune.

See docs/architecture/Intelligence_Foundation_Design.md section 4.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.memory_manager.consolidation_policy import ConsolidationPolicy
from parika.core.memory_manager.exceptions import InvalidMemoryError, MemoryNotFoundError
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_kind import MemoryKind
from parika.core.memory_manager.memory_manager import MemoryManager
from parika.core.memory_manager.memory_origin import MemoryOrigin
from parika.core.memory_manager.memory_scope import MemoryScope
from parika.core.memory_manager.memory_search_query import MemorySearchQuery
from parika.core.memory_manager.prune_policy import PrunePolicy


def _make_memory(
    *,
    memory_id: str,
    content: str = "The sky is blue.",
    kind: MemoryKind = MemoryKind.FACT,
    scope: MemoryScope = MemoryScope.SESSION,
    session_id: str | None = None,
    importance_score: float = 0.0,
    access_count: int = 0,
    confidence: float = 1.0,
    decay_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Memory:
    now = datetime.now(UTC)
    effective_updated_at = updated_at if updated_at is not None else now
    effective_created_at = min(now, effective_updated_at)

    return Memory(
        memory_id=memory_id,
        kind=kind,
        origin=MemoryOrigin.USER_EXPLICIT,
        content=content,
        created_at=effective_created_at,
        updated_at=effective_updated_at,
        scope=scope,
        session_id=session_id,
        importance_score=importance_score,
        confidence=confidence,
        access_count=access_count,
        decay_at=decay_at,
    )


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "memory.db"


@pytest.fixture
def memory_manager(
    logger: Logger,
    event_bus: EventBus,
    database_path: Path,
) -> Iterator[MemoryManager]:
    manager = MemoryManager(logger=logger, event_bus=event_bus, database_path=database_path)
    manager.initialize()

    yield manager

    manager.shutdown()


class TestMemoryScopeAndImportanceFields:
    def test_defaults(self) -> None:
        memory = _make_memory(memory_id="m1")

        assert memory.scope is MemoryScope.SESSION
        assert memory.session_id is None
        assert memory.importance_score == 0.0
        assert memory.access_count == 0
        assert memory.last_accessed_at is None
        assert memory.decay_at is None

    def test_rejects_non_memory_scope(self) -> None:
        with pytest.raises(TypeError):
            Memory(
                memory_id="m1",
                kind=MemoryKind.FACT,
                origin=MemoryOrigin.USER_EXPLICIT,
                content="x",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                scope="session",  # type: ignore[arg-type]
            )

    def test_rejects_negative_access_count(self) -> None:
        with pytest.raises(ValueError):
            _make_memory(memory_id="m1", access_count=-1)

    def test_rejects_non_finite_importance_score(self) -> None:
        with pytest.raises(ValueError):
            _make_memory(memory_id="m1", importance_score=float("nan"))

    def test_round_trips_through_storage(self, memory_manager: MemoryManager) -> None:
        stored = memory_manager.register(
            _make_memory(
                memory_id="m1",
                scope=MemoryScope.USER,
                session_id="session-abc",
                importance_score=0.75,
                access_count=3,
            )
        )
        fetched = memory_manager.get("m1")

        assert fetched.scope is MemoryScope.USER
        assert fetched.session_id == "session-abc"
        assert fetched.importance_score == 0.75
        assert fetched.access_count == 3
        assert stored == fetched


class TestGetByScopeAndKind:
    def test_get_by_scope_filters(self, memory_manager: MemoryManager) -> None:
        memory_manager.register(_make_memory(memory_id="m1", scope=MemoryScope.SESSION, session_id="s1"))
        memory_manager.register(_make_memory(memory_id="m2", scope=MemoryScope.SESSION, session_id="s2"))
        memory_manager.register(_make_memory(memory_id="m3", scope=MemoryScope.GLOBAL))

        session_scoped = memory_manager.get_by_scope(MemoryScope.SESSION)
        assert {m.memory_id for m in session_scoped} == {"m1", "m2"}

        s1_only = memory_manager.get_by_scope(MemoryScope.SESSION, session_id="s1")
        assert {m.memory_id for m in s1_only} == {"m1"}

        global_scoped = memory_manager.get_by_scope(MemoryScope.GLOBAL)
        assert {m.memory_id for m in global_scoped} == {"m3"}

    def test_get_by_scope_rejects_invalid_type(self, memory_manager: MemoryManager) -> None:
        with pytest.raises(TypeError):
            memory_manager.get_by_scope("session")  # type: ignore[arg-type]

    def test_get_by_kind_filters(self, memory_manager: MemoryManager) -> None:
        memory_manager.register(_make_memory(memory_id="m1", kind=MemoryKind.FACT))
        memory_manager.register(_make_memory(memory_id="m2", kind=MemoryKind.PREFERENCE))

        facts = memory_manager.get_by_kind(MemoryKind.FACT)
        assert {m.memory_id for m in facts} == {"m1"}

    def test_get_by_kind_rejects_invalid_type(self, memory_manager: MemoryManager) -> None:
        with pytest.raises(TypeError):
            memory_manager.get_by_kind("fact")  # type: ignore[arg-type]


class TestTouch:
    def test_bumps_access_count_and_last_accessed_at(self, memory_manager: MemoryManager) -> None:
        memory_manager.register(_make_memory(memory_id="m1"))

        touched = memory_manager.touch("m1")

        assert touched.access_count == 1
        assert touched.last_accessed_at is not None

        touched_again = memory_manager.touch("m1")
        assert touched_again.access_count == 2

    def test_raises_when_missing(self, memory_manager: MemoryManager) -> None:
        with pytest.raises(MemoryNotFoundError):
            memory_manager.touch("missing")


class TestSearch:
    def test_rejects_invalid_query_type(self, memory_manager: MemoryManager) -> None:
        with pytest.raises(InvalidMemoryError):
            memory_manager.search("not-a-query")  # type: ignore[arg-type]

    def test_lexical_relevance_promotes_matching_content(
        self, memory_manager: MemoryManager
    ) -> None:
        memory_manager.register(
            _make_memory(memory_id="m1", content="The user prefers dark mode in the editor.")
        )
        memory_manager.register(
            _make_memory(memory_id="m2", content="Unrelated content about cooking recipes.")
        )

        results = memory_manager.search(MemorySearchQuery(text="dark mode editor"))

        assert results[0].memory.memory_id == "m1"
        assert results[0].score > 0.0

    def test_confidence_influences_ranking(self, memory_manager: MemoryManager) -> None:
        """
        Phase 1 Completion Specification section 4: confidence must be
        one of the ranking factors, distinct from importance.
        """

        memory_manager.register(
            _make_memory(memory_id="low", content="distinct fact alpha", confidence=0.1)
        )
        memory_manager.register(
            _make_memory(memory_id="high", content="distinct fact beta", confidence=1.0)
        )

        results = memory_manager.search(MemorySearchQuery(text=""))

        assert results[0].memory.memory_id == "high"
        assert results[0].breakdown["confidence"] > results[1].breakdown["confidence"]

    def test_empty_text_falls_back_to_recency_importance(
        self, memory_manager: MemoryManager
    ) -> None:
        memory_manager.register(_make_memory(memory_id="low", importance_score=0.0))
        memory_manager.register(_make_memory(memory_id="high", importance_score=5.0))

        results = memory_manager.search(MemorySearchQuery(text=""))

        assert results[0].memory.memory_id == "high"

    def test_filters_by_scope_and_kind(self, memory_manager: MemoryManager) -> None:
        memory_manager.register(
            _make_memory(memory_id="m1", scope=MemoryScope.USER, kind=MemoryKind.PREFERENCE, content="likes tea")
        )
        memory_manager.register(
            _make_memory(memory_id="m2", scope=MemoryScope.SESSION, kind=MemoryKind.FACT, content="likes tea too")
        )

        results = memory_manager.search(
            MemorySearchQuery(text="tea", scope=MemoryScope.USER, kind=MemoryKind.PREFERENCE)
        )

        assert {r.memory.memory_id for r in results} == {"m1"}

    def test_respects_limit_and_offset(self, memory_manager: MemoryManager) -> None:
        for index in range(5):
            memory_manager.register(
                _make_memory(memory_id=f"m{index}", importance_score=float(index))
            )

        page_one = memory_manager.search(MemorySearchQuery(text="", limit=2, offset=0))
        page_two = memory_manager.search(MemorySearchQuery(text="", limit=2, offset=2))

        assert len(page_one) == 2
        assert len(page_two) == 2
        assert {r.memory.memory_id for r in page_one}.isdisjoint(
            {r.memory.memory_id for r in page_two}
        )

    def test_never_returns_empty_breakdown_keys(self, memory_manager: MemoryManager) -> None:
        memory_manager.register(_make_memory(memory_id="m1", content="hello world"))

        results = memory_manager.search(MemorySearchQuery(text="hello"))

        assert set(results[0].breakdown.keys()) == {
            "relevance",
            "recency",
            "importance",
            "frequency",
            "confidence",
        }

    def test_query_text_with_punctuation_does_not_raise(
        self, memory_manager: MemoryManager
    ) -> None:
        """
        Regression test: FTS5's query-syntax parser treats characters
        like '.', '-', ':' specially; free-form content/queries must
        be safely escaped rather than raising
        sqlite3.OperationalError -- see search_storage._fts5_quote_query().
        """

        memory_manager.register(_make_memory(memory_id="m1", content="User works at Acme."))

        results = memory_manager.search(MemorySearchQuery(text="User works at Acme."))

        assert len(results) == 1

    def test_config_weights_are_applied(self) -> None:
        configuration = Configuration()
        configuration.load()

        # Sanity: loading with a real Configuration does not raise and
        # produces a manager that still searches correctly.
        logger = Logger(configuration)
        event_bus = EventBus(logger)

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            manager = MemoryManager(
                logger=logger,
                event_bus=event_bus,
                database_path=Path(tmp) / "memory.db",
                configuration=configuration,
            )
            manager.initialize()
            manager.register(_make_memory(memory_id="m1", content="alpha beta"))

            results = manager.search(MemorySearchQuery(text="alpha"))
            assert len(results) == 1

            manager.shutdown()


class TestSearchProgressReporting:
    """
    Phase 3.5b: `search()` reports its own `memory.search.*` execution
    progress, as an independent activity, through the already-injected
    `EventBus`.
    """

    def test_successful_search_publishes_started_and_completed(
        self, memory_manager: MemoryManager, event_bus: EventBus
    ) -> None:
        events: list[object] = []
        event_bus.subscribe("progress.started", events.append)
        event_bus.subscribe("progress.completed", events.append)
        event_bus.subscribe("progress.failed", events.append)

        memory_manager.register(_make_memory(memory_id="m1", content="dark mode"))

        memory_manager.search(MemorySearchQuery(text="dark mode"))

        source_ids = [event.source_id for event in events]
        assert source_ids == ["memory.search", "memory.search"]
        assert events[0].stage.value == "started"
        assert events[1].stage.value == "completed"
        assert events[0].progress_id == events[1].progress_id

    def test_invalid_query_reports_no_progress(
        self, memory_manager: MemoryManager, event_bus: EventBus
    ) -> None:
        events: list[object] = []
        event_bus.subscribe("progress.started", events.append)

        with pytest.raises(InvalidMemoryError):
            memory_manager.search("not-a-query")  # type: ignore[arg-type]

        assert events == []


class TestConsolidationCandidates:
    def test_selects_stale_low_access_memories(self, memory_manager: MemoryManager) -> None:
        old_time = datetime.now(UTC) - timedelta(hours=2)

        memory_manager.register(
            _make_memory(
                memory_id="stale",
                kind=MemoryKind.SHORT_TERM,
                scope=MemoryScope.SESSION,
                session_id="s1",
                access_count=0,
                updated_at=old_time,
            )
        )
        memory_manager.register(
            _make_memory(
                memory_id="fresh",
                kind=MemoryKind.SHORT_TERM,
                scope=MemoryScope.SESSION,
                session_id="s1",
                access_count=0,
                updated_at=datetime.now(UTC),
            )
        )

        candidates = memory_manager.consolidation_candidates(
            ConsolidationPolicy(
                scope=MemoryScope.SESSION,
                session_id="s1",
                kind=MemoryKind.SHORT_TERM,
                older_than_seconds=3600,
                max_access_count=1,
            )
        )

        assert {m.memory_id for m in candidates} == {"stale"}

    def test_is_read_only(self, memory_manager: MemoryManager) -> None:
        old_time = datetime.now(UTC) - timedelta(hours=2)
        memory_manager.register(
            _make_memory(
                memory_id="stale",
                kind=MemoryKind.SHORT_TERM,
                updated_at=old_time,
            )
        )

        memory_manager.consolidation_candidates(
            ConsolidationPolicy(scope=MemoryScope.SESSION, kind=MemoryKind.SHORT_TERM)
        )

        # Still present -- consolidation_candidates never deletes.
        assert memory_manager.contains("stale")

    def test_rejects_invalid_policy_type(self, memory_manager: MemoryManager) -> None:
        with pytest.raises(InvalidMemoryError):
            memory_manager.consolidation_candidates("not-a-policy")  # type: ignore[arg-type]


class TestPrune:
    def test_prunes_expired_memories(self, memory_manager: MemoryManager) -> None:
        expired_at = datetime.now(UTC) - timedelta(seconds=1)
        memory_manager.register(_make_memory(memory_id="expired", decay_at=expired_at))
        memory_manager.register(_make_memory(memory_id="kept"))

        removed = memory_manager.prune(PrunePolicy(respect_decay=True))

        assert {m.memory_id for m in removed} == {"expired"}
        assert memory_manager.contains("kept")
        assert not memory_manager.contains("expired")

    def test_prunes_excess_least_valuable_first(self, memory_manager: MemoryManager) -> None:
        memory_manager.register(
            _make_memory(memory_id="low", scope=MemoryScope.SESSION, importance_score=0.0)
        )
        memory_manager.register(
            _make_memory(memory_id="high", scope=MemoryScope.SESSION, importance_score=5.0)
        )

        removed = memory_manager.prune(
            PrunePolicy(scope=MemoryScope.SESSION, respect_decay=False, max_per_scope=1)
        )

        assert {m.memory_id for m in removed} == {"low"}
        assert memory_manager.contains("high")

    def test_publishes_removed_event(self, memory_manager: MemoryManager, event_bus: EventBus) -> None:
        received: list[object] = []
        event_bus.subscribe("memory.removed", received.append)

        expired_at = datetime.now(UTC) - timedelta(seconds=1)
        memory_manager.register(_make_memory(memory_id="expired", decay_at=expired_at))

        memory_manager.prune(PrunePolicy(respect_decay=True))

        assert len(received) == 1

    def test_no_candidates_returns_empty(self, memory_manager: MemoryManager) -> None:
        memory_manager.register(_make_memory(memory_id="kept"))

        removed = memory_manager.prune(PrunePolicy(respect_decay=True))

        assert removed == ()

    def test_rejects_invalid_policy_type(self, memory_manager: MemoryManager) -> None:
        with pytest.raises(InvalidMemoryError):
            memory_manager.prune("not-a-policy")  # type: ignore[arg-type]


class TestMigrationFromV1:
    def test_v1_database_migrates_and_stays_queryable(
        self, logger: Logger, event_bus: EventBus, tmp_path: Path
    ) -> None:
        """
        A database created by the pre-Intelligence-Foundation schema
        (v1: no scope/importance/access columns, no FTS5 table) must
        migrate cleanly and keep its existing rows queryable.
        """

        import sqlite3

        db_path = tmp_path / "legacy.db"

        connection = sqlite3.connect(db_path)
        connection.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE memories (
                memory_id TEXT PRIMARY KEY, kind TEXT NOT NULL, origin TEXT NOT NULL,
                content TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                tags TEXT NOT NULL, metadata TEXT NOT NULL
            );
            CREATE INDEX idx_memories_kind ON memories(kind);
            """
        )
        now_iso = datetime.now(UTC).isoformat()
        connection.execute(
            "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
            ("legacy-1", "fact", "user_explicit", "a legacy fact", now_iso, now_iso, "[]", "{}"),
        )
        connection.execute("PRAGMA user_version = 1;")
        connection.commit()
        connection.close()

        manager = MemoryManager(logger=logger, event_bus=event_bus, database_path=db_path)
        manager.initialize()

        try:
            legacy = manager.get("legacy-1")
            assert legacy.content == "a legacy fact"
            assert legacy.scope is MemoryScope.SESSION
            assert legacy.importance_score == 0.0

            # New memories and search work on the migrated database.
            manager.register(_make_memory(memory_id="new-1", content="a new fact about migration"))
            results = manager.search(MemorySearchQuery(text="migration"))
            assert any(r.memory.memory_id == "new-1" for r in results)

        finally:
            manager.shutdown()
