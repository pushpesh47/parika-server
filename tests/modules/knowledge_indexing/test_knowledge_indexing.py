"""
Unit tests for the Knowledge Indexing Module: KnowledgeUnitStorage,
DocumentKnowledgeEngine, CodeKnowledgeEngine, and
KnowledgeIndexingModuleDriver.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.registry import KnowledgeEngineRegistry
from parika.core.knowledge_manager.search_query import SearchQuery
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.core.knowledge_manager.source_status import KnowledgeSourceStatus
from parika.core.knowledge_manager.sqlite_storage import SqliteKnowledgeStorage
from parika.core.logger.logger import Logger
from parika.modules.knowledge_indexing.code_engine import CodeKnowledgeEngine
from parika.modules.knowledge_indexing.content_hash import (
    compute_content_hash,
    iter_files,
)
from parika.modules.knowledge_indexing.document_engine import DocumentKnowledgeEngine
from parika.modules.knowledge_indexing.driver import KnowledgeIndexingModuleDriver
from parika.modules.knowledge_indexing.unit_storage import KnowledgeUnitStorage


def _make_source(location: str, kind: KnowledgeSourceKind) -> KnowledgeSource:
    return KnowledgeSource(
        id=uuid4(),
        name="test-source",
        kind=kind,
        location=location,
        status=KnowledgeSourceStatus.AVAILABLE,
    )


@pytest.fixture
def unit_storage(tmp_path: Path) -> Iterator[KnowledgeUnitStorage]:
    storage = KnowledgeUnitStorage(tmp_path / "units.db")
    storage.initialize()

    yield storage

    storage.shutdown()


class TestKnowledgeUnitStorage:
    def test_replace_and_search(self, unit_storage: KnowledgeUnitStorage) -> None:
        from parika.modules.knowledge_indexing.unit_storage import build_knowledge_unit

        source_id = uuid4()
        unit = build_knowledge_unit(
            source_id=source_id,
            title="A note about dark mode",
            content="The application supports a dark mode theme.",
            location="doc.md#0",
        )

        count = unit_storage.replace_units_for_source(source_id, [unit])
        assert count == 1

        results = unit_storage.search(
            source_ids=frozenset({source_id}), text="dark mode", limit=10
        )

        assert len(results) == 1
        assert results[0].knowledge.title == "A note about dark mode"
        assert results[0].score > 0.0

    def test_search_query_with_punctuation_does_not_raise(
        self, unit_storage: KnowledgeUnitStorage
    ) -> None:
        """
        Regression test: see the identical test/rationale in
        tests/core/memory_manager/test_memory_manager_search.py.
        """
        from parika.modules.knowledge_indexing.unit_storage import build_knowledge_unit

        source_id = uuid4()
        unit_storage.replace_units_for_source(
            source_id,
            [
                build_knowledge_unit(
                    source_id=source_id,
                    title="t",
                    content="User works at Acme.",
                    location="l",
                )
            ],
        )

        results = unit_storage.search(
            source_ids=frozenset({source_id}), text="User works at Acme.", limit=10
        )

        assert len(results) == 1

    def test_search_respects_source_id_filter(
        self, unit_storage: KnowledgeUnitStorage
    ) -> None:
        from parika.modules.knowledge_indexing.unit_storage import build_knowledge_unit

        source_a = uuid4()
        source_b = uuid4()

        unit_storage.replace_units_for_source(
            source_a,
            [build_knowledge_unit(source_id=source_a, title="A", content="alpha", location="a")],
        )
        unit_storage.replace_units_for_source(
            source_b,
            [build_knowledge_unit(source_id=source_b, title="B", content="alpha", location="b")],
        )

        results = unit_storage.search(
            source_ids=frozenset({source_a}), text="alpha", limit=10
        )

        assert {r.knowledge.source_id for r in results} == {source_a}

    def test_delete_units_for_source(self, unit_storage: KnowledgeUnitStorage) -> None:
        from parika.modules.knowledge_indexing.unit_storage import build_knowledge_unit

        source_id = uuid4()
        unit_storage.replace_units_for_source(
            source_id,
            [build_knowledge_unit(source_id=source_id, title="T", content="beta", location="l")],
        )

        unit_storage.delete_units_for_source(source_id)

        results = unit_storage.search(
            source_ids=frozenset({source_id}), text="beta", limit=10
        )
        assert results == ()

    def test_search_with_empty_source_ids_returns_empty(
        self, unit_storage: KnowledgeUnitStorage
    ) -> None:
        assert unit_storage.search(source_ids=frozenset(), text="x", limit=10) == ()


class TestDocumentKnowledgeEngine:
    def test_supports_document_kinds(self, unit_storage: KnowledgeUnitStorage) -> None:
        engine = DocumentKnowledgeEngine(unit_storage)

        assert engine.supports(_make_source("x", KnowledgeSourceKind.DOCUMENTATION))
        assert engine.supports(_make_source("x", KnowledgeSourceKind.DOCUMENT_COLLECTION))
        assert not engine.supports(_make_source("x", KnowledgeSourceKind.REPOSITORY))

    def test_indexes_and_searches_paragraphs(
        self, unit_storage: KnowledgeUnitStorage, tmp_path: Path
    ) -> None:
        doc_dir = tmp_path / "docs"
        doc_dir.mkdir()
        (doc_dir / "guide.md").write_text(
            "# Introduction\n\nThis project supports dark mode natively.\n\n"
            "## Advanced\n\nUse the CLI to configure advanced settings.\n",
            encoding="utf-8",
        )

        source = _make_source(str(doc_dir), KnowledgeSourceKind.DOCUMENTATION)
        engine = DocumentKnowledgeEngine(unit_storage)

        count = engine.index(source)
        assert count >= 2

        results = engine.search(
            (source,), SearchQuery(text="dark mode", limit=10)
        )
        assert len(results) >= 1

    def test_remove_deletes_units(
        self, unit_storage: KnowledgeUnitStorage, tmp_path: Path
    ) -> None:
        doc_dir = tmp_path / "docs2"
        doc_dir.mkdir()
        (doc_dir / "note.txt").write_text("Some searchable content here.\n", encoding="utf-8")

        source = _make_source(str(doc_dir), KnowledgeSourceKind.DOCUMENTATION)
        engine = DocumentKnowledgeEngine(unit_storage)
        engine.index(source)

        engine.remove(source)

        results = engine.search((source,), SearchQuery(text="searchable", limit=10))
        assert results == ()


class TestCodeKnowledgeEngine:
    def test_supports_code_kinds(self, unit_storage: KnowledgeUnitStorage) -> None:
        engine = CodeKnowledgeEngine(unit_storage)

        assert engine.supports(_make_source("x", KnowledgeSourceKind.REPOSITORY))
        assert engine.supports(_make_source("x", KnowledgeSourceKind.WORKSPACE))
        assert not engine.supports(_make_source("x", KnowledgeSourceKind.DOCUMENTATION))

    def test_extracts_functions_classes_and_imports(
        self, unit_storage: KnowledgeUnitStorage, tmp_path: Path
    ) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "sample.py").write_text(
            '"""Sample module docstring."""\n'
            "import os\n"
            "from collections import OrderedDict\n\n"
            "class Widget:\n"
            '    """A widget class."""\n'
            "    def render(self):\n"
            '        """Render the widget."""\n'
            "        return None\n\n"
            "def build_widget():\n"
            '    """Build a new widget."""\n'
            "    return Widget()\n",
            encoding="utf-8",
        )

        source = _make_source(str(repo_dir), KnowledgeSourceKind.REPOSITORY)
        engine = CodeKnowledgeEngine(unit_storage)

        count = engine.index(source)
        # module docstring + imports + Widget class + build_widget function
        assert count == 4

        results = engine.search((source,), SearchQuery(text="widget", limit=10))
        assert len(results) >= 1

    def test_skips_files_with_syntax_errors(
        self, unit_storage: KnowledgeUnitStorage, tmp_path: Path
    ) -> None:
        repo_dir = tmp_path / "broken_repo"
        repo_dir.mkdir()
        (repo_dir / "broken.py").write_text("def bad(:\n", encoding="utf-8")

        source = _make_source(str(repo_dir), KnowledgeSourceKind.REPOSITORY)
        engine = CodeKnowledgeEngine(unit_storage)

        # Must not raise -- syntax-invalid files are skipped.
        count = engine.index(source)
        assert count == 0


class TestContentHash:
    def test_deterministic_for_same_files(self, tmp_path: Path) -> None:
        file_path = tmp_path / "a.txt"
        file_path.write_text("hello", encoding="utf-8")

        first = compute_content_hash(iter_files(tmp_path))
        second = compute_content_hash(iter_files(tmp_path))

        assert first == second

    def test_changes_when_content_changes(self, tmp_path: Path) -> None:
        file_path = tmp_path / "a.txt"
        file_path.write_text("hello", encoding="utf-8")
        before = compute_content_hash(iter_files(tmp_path))

        file_path.write_text("hello world, now longer", encoding="utf-8")
        after = compute_content_hash(iter_files(tmp_path))

        assert before != after

    def test_iter_files_filters_by_suffix(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "b.md").write_text("x", encoding="utf-8")

        py_files = iter_files(tmp_path, suffixes=(".py",))

        assert [p.suffix for p in py_files] == [".py"]


class TestKnowledgeIndexingModuleDriver:
    def test_start_registers_both_engines_and_stop_unregisters(
        self, logger: Logger, event_bus: EventBus, tmp_path: Path
    ) -> None:
        storage = SqliteKnowledgeStorage(tmp_path / "sources.db")
        storage.initialize()

        knowledge_manager = KnowledgeManager(
            storage=storage,
            registry=KnowledgeEngineRegistry(),
            event_bus=event_bus,
            logger=logger,
        )

        driver = KnowledgeIndexingModuleDriver(
            knowledge_manager=knowledge_manager,
            logger=logger,
            database_path=tmp_path / "units.db",
        )

        driver.start()
        try:
            source = _make_source(
                str(tmp_path), KnowledgeSourceKind.REPOSITORY
            )
            knowledge_manager.register_source(source)
            knowledge_manager.index(source.id)
        finally:
            driver.stop()

        storage.shutdown()

    def test_health_check_reports_healthy(
        self, logger: Logger, event_bus: EventBus, tmp_path: Path
    ) -> None:
        storage = SqliteKnowledgeStorage(tmp_path / "sources.db")
        storage.initialize()

        knowledge_manager = KnowledgeManager(
            storage=storage,
            registry=KnowledgeEngineRegistry(),
            event_bus=event_bus,
            logger=logger,
        )

        driver = KnowledgeIndexingModuleDriver(
            knowledge_manager=knowledge_manager,
            logger=logger,
            database_path=tmp_path / "units.db",
        )

        result = driver._check_health()
        assert result.status.name == "HEALTHY"

        storage.shutdown()
