"""
Unit tests for MemoryManager's Phase 1 Completion Specification
extension: `remember()`, `forget()`, `merge()`, `list()`, `delete()`,
`clear()`, `stats()`, `export()`, `import_memories()`, and the new
`MemoryCategory`/`MemoryImportance`/`confidence` fields.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.memory_manager.exceptions import InvalidMemoryError, MemoryNotFoundError
from parika.core.memory_manager.memory_category import MemoryCategory
from parika.core.memory_manager.memory_importance import MemoryImportance
from parika.core.memory_manager.memory_manager import MemoryManager
from parika.core.memory_manager.memory_scope import MemoryScope


@pytest.fixture
def memory_manager(
    logger: Logger, event_bus: EventBus, tmp_path: Path
) -> Iterator[MemoryManager]:
    manager = MemoryManager(
        logger=logger, event_bus=event_bus, database_path=tmp_path / "memory.db"
    )
    manager.initialize()

    yield manager

    manager.shutdown()


class TestRemember:
    def test_creates_new_memory_when_no_duplicate(
        self, memory_manager: MemoryManager
    ) -> None:
        memory, created = memory_manager.remember(
            content="My name is Pushpesh.",
            category=MemoryCategory.PROFILE,
        )

        assert created is True
        assert memory.category is MemoryCategory.PROFILE
        assert memory.scope is MemoryScope.GLOBAL

    def test_defaults_to_global_scope(self, memory_manager: MemoryManager) -> None:
        memory, _ = memory_manager.remember(content="A fact about the user.")

        assert memory.scope is MemoryScope.GLOBAL

    def test_survives_as_a_distinct_row(self, memory_manager: MemoryManager) -> None:
        memory, _ = memory_manager.remember(content="My name is Pushpesh.")

        assert memory_manager.contains(memory.memory_id)

    def test_merges_near_duplicate_instead_of_creating_new_row(
        self, memory_manager: MemoryManager
    ) -> None:
        first, first_created = memory_manager.remember(
            content="User's name is Pushpesh.", category=MemoryCategory.PROFILE
        )
        second, second_created = memory_manager.remember(
            content="User's name is Pushpesh", category=MemoryCategory.PROFILE
        )

        assert first_created is True
        assert second_created is False
        assert second.memory_id == first.memory_id
        assert memory_manager.count() == 1

    def test_merge_adopts_the_new_restatement(
        self, memory_manager: MemoryManager
    ) -> None:
        """
        A near-duplicate restatement replaces the stale canonical
        content instead of being discarded, so the latest phrasing of
        an unchanged fact is always what gets kept (previously the
        *first* phrasing was kept forever regardless of later
        restatements). Genuine value updates -- where the new
        restatement introduces a brand new word not present at all in
        the old content (e.g. "Python" -> "Python 3.14") -- are
        handled by the structured-facts merge path instead (see
        `test_semantic_update_replaces_stale_value_without_duplicating`
        below), since the lexical candidate search this plain path
        relies on can only ever find a candidate whose indexed content
        already contains every term of the new restatement.
        """

        first, _ = memory_manager.remember(
            content="Name = Pushpesh", category=MemoryCategory.PROFILE
        )
        second, created = memory_manager.remember(
            content="Name: Pushpesh", category=MemoryCategory.PROFILE
        )

        assert created is False
        assert second.memory_id == first.memory_id
        assert second.content == "Name: Pushpesh"
        assert memory_manager.count() == 1

    def test_semantic_update_replaces_stale_value_without_duplicating(
        self, memory_manager: MemoryManager
    ) -> None:
        """
        PARIKA Memory Subsystem Refactor, Requirement D worked example:
        "Remember my preferred language is Python." followed later by
        "Remember my preferred language is Python 3.14." must update
        the existing memory (adopting "Python 3.14"), never create a
        second, separate memory.
        """

        first, first_created = memory_manager.remember(
            content="My preferred language is Python."
        )
        second, second_created = memory_manager.remember(
            content="My preferred language is Python 3.14."
        )

        assert first_created is True
        assert second_created is False
        assert second.memory_id == first.memory_id
        assert memory_manager.count() == 1
        assert "Python 3.14" in second.content
        assert second.metadata["slots"]["Language"] == "Python 3.14"

    def test_merge_increases_confidence(self, memory_manager: MemoryManager) -> None:
        first, _ = memory_manager.remember(
            content="User likes tea.",
            category=MemoryCategory.PREFERENCE,
            confidence=0.5,
        )
        second, _ = memory_manager.remember(
            content="User likes tea", category=MemoryCategory.PREFERENCE
        )

        assert second.confidence > first.confidence

    def test_different_categories_are_not_merged(
        self, memory_manager: MemoryManager
    ) -> None:
        memory_manager.remember(
            content="tea", category=MemoryCategory.PREFERENCE
        )
        _, created = memory_manager.remember(
            content="tea", category=MemoryCategory.FACT
        )

        assert created is True
        assert memory_manager.count() == 2

    def test_rejects_empty_content(self, memory_manager: MemoryManager) -> None:
        with pytest.raises(InvalidMemoryError):
            memory_manager.remember(content="   ")

    def test_importance_level_maps_to_importance_score(
        self, memory_manager: MemoryManager
    ) -> None:
        low, _ = memory_manager.remember(
            content="low importance fact one", importance=MemoryImportance.LOW
        )
        critical, _ = memory_manager.remember(
            content="critical importance fact two", importance=MemoryImportance.CRITICAL
        )

        assert critical.importance_score > low.importance_score

    def test_publishes_registered_event_on_create(
        self, memory_manager: MemoryManager, event_bus: EventBus
    ) -> None:
        received: list[object] = []
        event_bus.subscribe("memory.registered", received.append)

        memory_manager.remember(content="A brand new fact.")

        assert len(received) == 1


class TestForgetAndDelete(object):
    def test_forget_removes_memory(self, memory_manager: MemoryManager) -> None:
        memory, _ = memory_manager.remember(content="Temporary fact.")

        memory_manager.forget(memory.memory_id)

        assert not memory_manager.contains(memory.memory_id)

    def test_delete_is_an_alias_for_remove(self, memory_manager: MemoryManager) -> None:
        memory, _ = memory_manager.remember(content="Another fact.")

        memory_manager.delete(memory.memory_id)

        assert not memory_manager.contains(memory.memory_id)


class TestMerge:
    def test_merges_two_memories(self, memory_manager: MemoryManager) -> None:
        primary, _ = memory_manager.remember(
            content="User works at Acme.", category=MemoryCategory.PROJECT
        )
        secondary, _ = memory_manager.remember(
            content="User is employed by Acme Corp, a completely different phrasing.",
            category=MemoryCategory.PROJECT,
        )

        merged = memory_manager.merge(primary.memory_id, secondary.memory_id)

        assert merged.memory_id == primary.memory_id
        assert merged.content == primary.content
        assert not memory_manager.contains(secondary.memory_id)

    def test_raises_when_primary_missing(self, memory_manager: MemoryManager) -> None:
        secondary, _ = memory_manager.remember(content="x")

        with pytest.raises(MemoryNotFoundError):
            memory_manager.merge("missing", secondary.memory_id)

    def test_raises_when_secondary_missing(self, memory_manager: MemoryManager) -> None:
        primary, _ = memory_manager.remember(content="x")

        with pytest.raises(MemoryNotFoundError):
            memory_manager.merge(primary.memory_id, "missing")


class TestList:
    def test_filters_by_category(self, memory_manager: MemoryManager) -> None:
        memory_manager.remember(content="a profile fact", category=MemoryCategory.PROFILE)
        memory_manager.remember(content="a goal fact", category=MemoryCategory.GOAL)

        profiles = memory_manager.list(category=MemoryCategory.PROFILE)

        assert len(profiles) == 1
        assert profiles[0].category is MemoryCategory.PROFILE

    def test_respects_limit(self, memory_manager: MemoryManager) -> None:
        for i in range(5):
            memory_manager.remember(content=f"distinct fact number {i}")

        results = memory_manager.list(limit=2)

        assert len(results) == 2

    def test_rejects_invalid_limit(self, memory_manager: MemoryManager) -> None:
        with pytest.raises(InvalidMemoryError):
            memory_manager.list(limit=0)


class TestClear:
    def test_clears_everything_by_default(self, memory_manager: MemoryManager) -> None:
        memory_manager.remember(content="fact one")
        memory_manager.remember(content="fact two")

        removed = memory_manager.clear()

        assert len(removed) == 2
        assert memory_manager.count() == 0

    def test_clears_only_matching_category(self, memory_manager: MemoryManager) -> None:
        memory_manager.remember(content="a profile fact", category=MemoryCategory.PROFILE)
        memory_manager.remember(content="a goal fact", category=MemoryCategory.GOAL)

        removed = memory_manager.clear(category=MemoryCategory.PROFILE)

        assert len(removed) == 1
        assert memory_manager.count() == 1

    def test_publishes_removed_events(
        self, memory_manager: MemoryManager, event_bus: EventBus
    ) -> None:
        received: list[object] = []
        event_bus.subscribe("memory.removed", received.append)

        memory_manager.remember(content="fact one")
        memory_manager.clear()

        assert len(received) == 1


class TestStats:
    def test_reports_total_and_breakdowns(self, memory_manager: MemoryManager) -> None:
        memory_manager.remember(content="a profile fact", category=MemoryCategory.PROFILE)
        memory_manager.remember(content="a goal fact", category=MemoryCategory.GOAL)

        stats = memory_manager.stats()

        assert stats.total == 2
        assert stats.by_category["profile"] == 1
        assert stats.by_category["goal"] == 1

    def test_reports_storage_size(self, memory_manager: MemoryManager) -> None:
        memory_manager.remember(content="a fact")

        stats = memory_manager.stats()

        assert stats.storage_size_bytes > 0


class TestExportImport:
    def test_export_writes_json_file(
        self, memory_manager: MemoryManager, tmp_path: Path
    ) -> None:
        memory_manager.remember(content="an exportable fact")
        export_path = tmp_path / "export.json"

        count = memory_manager.export(export_path)

        assert count == 1
        assert export_path.exists()

    def test_import_restores_memories_into_a_fresh_manager(
        self, memory_manager: MemoryManager, tmp_path: Path, logger: Logger, event_bus: EventBus
    ) -> None:
        memory_manager.remember(content="a fact to migrate", category=MemoryCategory.FACT)
        export_path = tmp_path / "export.json"
        memory_manager.export(export_path)

        fresh_manager = MemoryManager(
            logger=logger, event_bus=event_bus, database_path=tmp_path / "fresh.db"
        )
        fresh_manager.initialize()

        try:
            imported = fresh_manager.import_memories(export_path)

            assert imported == 1
            assert fresh_manager.count() == 1
            restored = fresh_manager.get_all()[0]
            assert restored.content == "a fact to migrate"
            assert restored.category is MemoryCategory.FACT
        finally:
            fresh_manager.shutdown()

    def test_import_skip_on_duplicate_leaves_existing_untouched(
        self, memory_manager: MemoryManager, tmp_path: Path
    ) -> None:
        memory, _ = memory_manager.remember(content="original content")
        export_path = tmp_path / "export.json"
        memory_manager.export(export_path)

        memory_manager.import_memories(export_path, on_duplicate="skip")

        assert memory_manager.get(memory.memory_id).content == "original content"

    def test_export_import_round_trip_preserves_field_count(
        self, memory_manager: MemoryManager, tmp_path: Path
    ) -> None:
        memory_manager.remember(content="fact one")
        memory_manager.remember(content="fact two")
        export_path = tmp_path / "export.json"

        memory_manager.export(export_path)
        memory_manager.clear()
        imported = memory_manager.import_memories(export_path)

        assert imported == 2
        assert memory_manager.count() == 2
