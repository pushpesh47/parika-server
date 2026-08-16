"""
Unit tests for RepositoryKnowledgeEngine.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.registry import KnowledgeEngineRegistry
from parika.core.knowledge_manager.search_query import SearchQuery
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.core.knowledge_manager.source_status import KnowledgeSourceStatus
from parika.core.knowledge_manager.sqlite_storage import SqliteKnowledgeStorage
from parika.modules.knowledge_indexing.document_engine import DocumentKnowledgeEngine
from parika.modules.knowledge_indexing.unit_storage import KnowledgeUnitStorage
from parika.modules.repository_intelligence.indexing.repository_knowledge_engine import (
    RepositoryKnowledgeEngine,
)
from parika.tools.coding.analyzers.registry import LanguageAnalyzerRegistry
from parika.tools.coding.storage import CodingIndexStorage


@pytest.fixture()
def coding_storage(tmp_path: Path) -> CodingIndexStorage:
    instance = CodingIndexStorage(tmp_path / "coding_index.sqlite3")
    instance.initialize()
    yield instance
    instance.shutdown()


@pytest.fixture()
def knowledge_manager(tmp_path: Path, logger, event_bus) -> KnowledgeManager:
    storage = SqliteKnowledgeStorage(database_path=tmp_path / "knowledge.sqlite3")
    storage.initialize()
    manager = KnowledgeManager(
        storage=storage, registry=KnowledgeEngineRegistry(), event_bus=event_bus, logger=logger
    )
    unit_storage = KnowledgeUnitStorage(tmp_path / "knowledge_units.sqlite3")
    unit_storage.initialize()
    manager.register_engine(DocumentKnowledgeEngine(unit_storage))
    return manager


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    repo = root / "myrepo"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "README.md").write_text("# My Repo\n\nA sample repository.\n", encoding="utf-8")
    (repo / "app.py").write_text(
        '"""App module."""\n\n\ndef main():\n    """Entry point."""\n    return 1\n',
        encoding="utf-8",
    )
    return root


def _register_workspace_source(knowledge_manager: KnowledgeManager, location: Path):
    source = KnowledgeSource(
        id=uuid4(),
        name="workspace",
        kind=KnowledgeSourceKind.WORKSPACE,
        location=str(location),
        status=KnowledgeSourceStatus.AVAILABLE,
    )
    knowledge_manager.register_source(source)
    return source


def test_index_populates_coding_storage(
    coding_storage: CodingIndexStorage,
    knowledge_manager: KnowledgeManager,
    repo_root: Path,
) -> None:
    engine = RepositoryKnowledgeEngine(
        coding_storage=coding_storage,
        analyzer_registry=LanguageAnalyzerRegistry(),
        knowledge_manager=knowledge_manager,
        max_file_size_bytes=2_000_000,
    )
    knowledge_manager.register_engine(engine)

    source = _register_workspace_source(knowledge_manager, repo_root)
    count = knowledge_manager.index(source.id) if False else engine.index(source)

    assert count > 0
    symbols = coding_storage.symbols_for_file(str(repo_root / "myrepo" / "app.py"))
    assert any(symbol.name == "main" for symbol in symbols)


def test_index_registers_readme_as_documentation_source(
    coding_storage: CodingIndexStorage,
    knowledge_manager: KnowledgeManager,
    repo_root: Path,
) -> None:
    engine = RepositoryKnowledgeEngine(
        coding_storage=coding_storage,
        analyzer_registry=LanguageAnalyzerRegistry(),
        knowledge_manager=knowledge_manager,
        max_file_size_bytes=2_000_000,
    )
    knowledge_manager.register_engine(engine)

    source = _register_workspace_source(knowledge_manager, repo_root)
    engine.index(source)

    readme_sources = [
        s
        for s in knowledge_manager.get_sources()
        if s.kind is KnowledgeSourceKind.DOCUMENTATION
    ]
    assert len(readme_sources) == 1
    assert readme_sources[0].location.endswith("README.md")


def test_search_finds_readme_content_via_knowledge_manager(
    coding_storage: CodingIndexStorage,
    knowledge_manager: KnowledgeManager,
    repo_root: Path,
) -> None:
    engine = RepositoryKnowledgeEngine(
        coding_storage=coding_storage,
        analyzer_registry=LanguageAnalyzerRegistry(),
        knowledge_manager=knowledge_manager,
        max_file_size_bytes=2_000_000,
    )
    knowledge_manager.register_engine(engine)

    source = _register_workspace_source(knowledge_manager, repo_root)
    engine.index(source)

    results = knowledge_manager.search(SearchQuery(text="sample repository", limit=10))
    assert len(results) >= 1


def test_reindexing_readme_is_idempotent(
    coding_storage: CodingIndexStorage,
    knowledge_manager: KnowledgeManager,
    repo_root: Path,
) -> None:
    engine = RepositoryKnowledgeEngine(
        coding_storage=coding_storage,
        analyzer_registry=LanguageAnalyzerRegistry(),
        knowledge_manager=knowledge_manager,
        max_file_size_bytes=2_000_000,
    )
    knowledge_manager.register_engine(engine)

    source = _register_workspace_source(knowledge_manager, repo_root)
    engine.index(source)
    engine.index(source)  # must not raise KnowledgeSourceAlreadyExistsError

    readme_sources = [
        s
        for s in knowledge_manager.get_sources()
        if s.kind is KnowledgeSourceKind.DOCUMENTATION
    ]
    assert len(readme_sources) == 1
