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
from tests.conftest_db import build_test_db_config

from pathlib import Path
from uuid import uuid4

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.registry import KnowledgeEngineRegistry
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.core.knowledge_manager.source_status import KnowledgeSourceStatus
from parika.core.knowledge_manager.postgresql_storage import PostgreSQLKnowledgeStorage
from parika.core.utilities.progress import ProgressEvent, ProgressReporter
from parika.modules.knowledge_indexing.document_engine import DocumentKnowledgeEngine
from parika.modules.knowledge_indexing.postgresql_unit_storage import PostgreSQLKnowledgeUnitStorage
from parika.modules.repository_intelligence.indexing import (
    repository_knowledge_engine as repository_knowledge_engine_module,
)
from parika.modules.repository_intelligence.indexing.repository_knowledge_engine import (
    RepositoryKnowledgeEngine,
)
from parika.tools.coding.analyzers.registry import LanguageAnalyzerRegistry
from parika.tools.coding.postgresql_storage import PostgreSQLCodingIndexStorage
from parika.core.database.pool import PoolManager
import parika.core.database.config as db_config_module
from parika.core.database.config import DatabaseConfig


# Test database configuration
# Test database configuration from environment
# TEST_DATABASE_CONFIG = { ... }  # Replaced by build_test_db_config()


@pytest.fixture(scope="session")
def _test_db_pool():
    """Initialize PostgreSQL test pool for the test session."""
    db_config = build_test_db_config()
    pool = PoolManager.initialize_sync_pool(db_config)
    yield pool
    PoolManager.shutdown_sync_pool()


@pytest.fixture()
def coding_storage(_test_db_pool) -> PostgreSQLCodingIndexStorage:
    instance = PostgreSQLCodingIndexStorage(_test_db_pool)
    instance.initialize()
    yield instance
    instance.shutdown()


@pytest.fixture()
def knowledge_manager(_test_db_pool, logger, event_bus) -> KnowledgeManager:
    storage = PostgreSQLKnowledgeStorage(_test_db_pool)
    storage.initialize()
    manager = KnowledgeManager(
        storage=storage, registry=KnowledgeEngineRegistry(), event_bus=event_bus, logger=logger
    )
    unit_storage = PostgreSQLKnowledgeUnitStorage(_test_db_pool)
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
