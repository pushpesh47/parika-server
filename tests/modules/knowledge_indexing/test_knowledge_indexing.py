"""
Unit tests for the Knowledge Indexing Module: PostgreSQLKnowledgeUnitStorage,
DocumentKnowledgeEngine, CodeKnowledgeEngine, and
KnowledgeIndexingModuleDriver.
"""


from __future__ import annotations
from tests.conftest_db import build_test_db_config

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
from parika.core.knowledge_manager.postgresql_storage import PostgreSQLKnowledgeStorage
from parika.core.logger.logger import Logger
from parika.modules.knowledge_indexing.code_engine import CodeKnowledgeEngine
from parika.modules.knowledge_indexing.content_hash import (
    compute_content_hash,
    iter_files,
)
from parika.modules.knowledge_indexing.document_engine import DocumentKnowledgeEngine
from parika.modules.knowledge_indexing.driver import KnowledgeIndexingModuleDriver
from parika.modules.knowledge_indexing.postgresql_unit_storage import PostgreSQLKnowledgeUnitStorage
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


def _make_source(location: str, kind: KnowledgeSourceKind) -> KnowledgeSource:
    return KnowledgeSource(
        id=uuid4(),
        name="test-source",
        kind=kind,
        location=location,
        status=KnowledgeSourceStatus.AVAILABLE,
    )


@pytest.fixture
def unit_storage(_test_db_pool) -> Iterator[PostgreSQLKnowledgeUnitStorage]:
    storage = PostgreSQLKnowledgeUnitStorage(_test_db_pool)
    storage.initialize()

    yield storage

    storage.shutdown()


class TestPostgreSQLKnowledgeUnitStorage:
    def test_replace_and_search(self, unit_storage: PostgreSQLKnowledgeUnitStorage) -> None:
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
        self, unit_storage: PostgreSQLKnowledgeUnitStorage
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
        # Should not raise FTS5 syntax error

    def test_delete_units_for_source(self, unit_storage: PostgreSQLKnowledgeUnitStorage) -> None:
        from parika.modules.knowledge_indexing.unit_storage import build_knowledge_unit

        source_id = uuid4()
        unit_storage.replace_units_for_source(
            source_id,
            [
                build_knowledge_unit(
                    source_id=source_id,
                    title="t",
                    content="Will be deleted",
                    location="l",
                )
            ],
        )
        assert len(unit_storage.search(source_ids=frozenset({source_id}), text="deleted", limit=10)) == 1

        unit_storage.delete_units_for_source(source_id)
        assert len(unit_storage.search(source_ids=frozenset({source_id}), text="deleted", limit=10)) == 0
