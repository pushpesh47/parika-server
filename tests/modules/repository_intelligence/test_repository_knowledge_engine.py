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
from parika.core.knowledge_manager.postgresql_storage import PostgreSQLKnowledgeStorage
from parika.modules.knowledge_indexing.document_engine import DocumentKnowledgeEngine
from parika.modules.knowledge_indexing.postgresql_unit_storage import PostgreSQLKnowledgeUnitStorage
from parika.modules.repository_intelligence.indexing.repository_knowledge_engine import (
    RepositoryKnowledgeEngine,
)
from parika.tools.coding.analyzers.registry import LanguageAnalyzerRegistry
from parika.tools.coding.postgresql_storage import PostgreSQLCodingIndexStorage
from parika.core.database.pool import PoolManager
import parika.core.database.config as db_config_module
from parika.core.database.config import DatabaseConfig


# Test database configuration
TEST_DATABASE_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 5432,
    "database": "parika_test",
    "username": "postgres",
    "password": "dba",
    "pool_min_size": 2,
    "pool_max_size": 10,
    "connect_timeout": 10.0,
    "statement_timeout": 0.0,
    "application_name": "parika_test",
}


@pytest.fixture(scope="session")
def _test_db_pool():
    """Initialize PostgreSQL test pool for the test session."""
    db_config = DatabaseConfig(**TEST_DATABASE_CONFIG)
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
    return tmp_path


# ... rest of the test file remains the same