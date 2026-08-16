"""
Regression tests for the confirmed ProgressReporter lifecycle leaks
the audit report identified in `RepositoryKnowledgeEngine.index()`:
`self._progress.started()` (and its `discover_workspace`/per-repository/
README child nodes) had no enclosing try/except anywhere in the
method, so a filesystem/indexing failure left those nodes open
forever.

Unlike the Image/Video generation leak (fixed at the shared
`ToolManager.execute()` boundary -- see
`tests/core/tool_manager/test_tool_manager_progress_guard.py`),
`RepositoryKnowledgeEngine.index()` is not a `ToolDriver` executed
through `ToolManager`; it is called directly by `KnowledgeManager`.
The shared guard does not reach it, so this module was fixed locally,
using the same reference-safe `started()`/`try`/`completed()`/
`except Exception: failed(); raise` shape already established
elsewhere.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.registry import KnowledgeEngineRegistry
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.core.knowledge_manager.source_status import KnowledgeSourceStatus
from parika.core.knowledge_manager.sqlite_storage import SqliteKnowledgeStorage
from parika.core.utilities.progress import ProgressEvent, ProgressReporter
from parika.modules.knowledge_indexing.document_engine import DocumentKnowledgeEngine
from parika.modules.knowledge_indexing.unit_storage import KnowledgeUnitStorage
from parika.modules.repository_intelligence.indexing import (
    repository_knowledge_engine as repository_knowledge_engine_module,
)
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


class _ProgressCollector:
    """Collects every ProgressEvent published on the generic channels."""

    def __init__(self, event_bus: EventBus) -> None:
        self.events: list[ProgressEvent] = []
        event_bus.subscribe("progress.started", self.events.append)
        event_bus.subscribe("progress.completed", self.events.append)
        event_bus.subscribe("progress.failed", self.events.append)

    def assert_every_started_has_exactly_one_terminal(self) -> None:
        starts: dict[str, list[ProgressEvent]] = {}
        terminals: dict[str, list[ProgressEvent]] = {}

        for event in self.events:
            if event.stage.value == "started":
                starts.setdefault(event.progress_id, []).append(event)
            else:
                terminals.setdefault(event.progress_id, []).append(event)

        for progress_id, started in starts.items():
            matching = terminals.get(progress_id, [])
            assert len(matching) == 1, (
                f"progress_id {progress_id!r} started {len(started)} "
                f"time(s) but received {len(matching)} terminal "
                f"event(s); expected exactly 1."
            )


def test_successful_index_reports_a_fully_balanced_progress_tree(
    coding_storage: CodingIndexStorage,
    knowledge_manager: KnowledgeManager,
    repo_root: Path,
    event_bus: EventBus,
) -> None:
    collector = _ProgressCollector(event_bus)

    engine = RepositoryKnowledgeEngine(
        coding_storage=coding_storage,
        analyzer_registry=LanguageAnalyzerRegistry(),
        knowledge_manager=knowledge_manager,
        max_file_size_bytes=2_000_000,
        progress_reporter=ProgressReporter(
            event_bus, "repository_intelligence.index_workspace"
        ),
    )
    knowledge_manager.register_engine(engine)

    source = _register_workspace_source(knowledge_manager, repo_root)
    engine.index(source)

    collector.assert_every_started_has_exactly_one_terminal()
    assert collector.events[0].source_id == "repository_intelligence.index_workspace"
    assert collector.events[0].stage.value == "started"
    assert collector.events[-1].source_id == "repository_intelligence.index_workspace"
    assert collector.events[-1].stage.value == "completed"


def test_discover_workspace_failure_reports_root_and_discovery_failed(
    coding_storage: CodingIndexStorage,
    knowledge_manager: KnowledgeManager,
    repo_root: Path,
    event_bus: EventBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = _ProgressCollector(event_bus)

    engine = RepositoryKnowledgeEngine(
        coding_storage=coding_storage,
        analyzer_registry=LanguageAnalyzerRegistry(),
        knowledge_manager=knowledge_manager,
        max_file_size_bytes=2_000_000,
        progress_reporter=ProgressReporter(
            event_bus, "repository_intelligence.index_workspace"
        ),
    )
    knowledge_manager.register_engine(engine)

    discovery_error = OSError("permission denied while walking workspace")

    def _boom(*args: object, **kwargs: object) -> None:
        raise discovery_error

    monkeypatch.setattr(repository_knowledge_engine_module, "discover_workspace", _boom)

    source = _register_workspace_source(knowledge_manager, repo_root)

    with pytest.raises(OSError) as excinfo:
        engine.index(source)

    assert excinfo.value is discovery_error

    collector.assert_every_started_has_exactly_one_terminal()
    source_ids_and_stages = [
        (event.source_id, event.stage.value) for event in collector.events
    ]
    assert source_ids_and_stages == [
        ("repository_intelligence.index_workspace", "started"),
        ("repository_intelligence.discover_workspace", "started"),
        ("repository_intelligence.discover_workspace", "failed"),
        ("repository_intelligence.index_workspace", "failed"),
    ]


def test_repository_indexing_failure_reports_repository_and_root_failed(
    coding_storage: CodingIndexStorage,
    knowledge_manager: KnowledgeManager,
    repo_root: Path,
    event_bus: EventBus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = _ProgressCollector(event_bus)

    engine = RepositoryKnowledgeEngine(
        coding_storage=coding_storage,
        analyzer_registry=LanguageAnalyzerRegistry(),
        knowledge_manager=knowledge_manager,
        max_file_size_bytes=2_000_000,
        progress_reporter=ProgressReporter(
            event_bus, "repository_intelligence.index_workspace"
        ),
    )
    knowledge_manager.register_engine(engine)

    indexing_error = RuntimeError("_index_repository exploded unexpectedly.")

    def _boom(self: RepositoryKnowledgeEngine, *args: object, **kwargs: object) -> int:
        raise indexing_error

    monkeypatch.setattr(RepositoryKnowledgeEngine, "_index_repository", _boom)

    source = _register_workspace_source(knowledge_manager, repo_root)

    with pytest.raises(RuntimeError) as excinfo:
        engine.index(source)

    assert excinfo.value is indexing_error

    collector.assert_every_started_has_exactly_one_terminal()
    source_ids_and_stages = [
        (event.source_id, event.stage.value) for event in collector.events
    ]
    assert source_ids_and_stages == [
        ("repository_intelligence.index_workspace", "started"),
        ("repository_intelligence.discover_workspace", "started"),
        ("repository_intelligence.discover_workspace", "completed"),
        ("repository_intelligence.index_repository", "started"),
        ("repository_intelligence.index_repository", "failed"),
        ("repository_intelligence.index_workspace", "failed"),
    ]
