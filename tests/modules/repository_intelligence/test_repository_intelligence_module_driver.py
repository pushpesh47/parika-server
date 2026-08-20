"""
Unit tests for RepositoryIntelligenceModuleDriver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.registry import KnowledgeEngineRegistry
from parika.core.knowledge_manager.postgresql_storage import PostgreSQLKnowledgeStorage
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.coding.driver import CodingModuleDriver
from parika.modules.repository_intelligence.driver import (
    RepositoryIntelligenceModuleDriver,
)
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
def knowledge_manager(_test_db_pool, logger, event_bus) -> KnowledgeManager:
    storage = PostgreSQLKnowledgeStorage(_test_db_pool)
    storage.initialize()
    return KnowledgeManager(
        storage=storage, registry=KnowledgeEngineRegistry(), event_bus=event_bus, logger=logger
    )


@pytest.fixture()
def coding_module(_test_db_pool, logger, event_bus) -> CodingModuleDriver:
    capability_registry = CapabilityRegistry(event_bus, logger)
    tool_manager = ToolManager(event_bus, logger)
    driver = CodingModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        database_path=_test_db_pool,  # PostgreSQL pool
        event_bus=event_bus,
    )
    driver.start()
    yield driver
    driver.stop()


def test_start_registers_engine_with_knowledge_manager(
    knowledge_manager: KnowledgeManager,
    coding_module: CodingModuleDriver,
    logger,
    event_bus,
    tmp_path: Path,
) -> None:
    tool_manager = ToolManager(event_bus, logger)

    driver = RepositoryIntelligenceModuleDriver(
        knowledge_manager=knowledge_manager,
        coding_storage=coding_module.storage,
        analyzer_registry=coding_module.registry,
        max_file_size_bytes=2_000_000,
        tool_manager=tool_manager,
        logger=logger,
        event_bus=event_bus,
    )

    assert knowledge_manager.count_engines() == 0
    driver.start()
    assert knowledge_manager.count_engines() == 1
    driver.stop()
    assert knowledge_manager.count_engines() == 0


def test_index_workspace_registers_source_and_indexes(
    knowledge_manager: KnowledgeManager,
    coding_module: CodingModuleDriver,
    logger,
    event_bus,
    tmp_path: Path,
) -> None:
    tool_manager = ToolManager(event_bus, logger)
    driver = RepositoryIntelligenceModuleDriver(
        knowledge_manager=knowledge_manager,
        coding_storage=coding_module.storage,
        analyzer_registry=coding_module.registry,
        max_file_size_bytes=2_000_000,
        tool_manager=tool_manager,
        logger=logger,
        event_bus=event_bus,
    )
    driver.start()

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "main.py").write_text("def entry():\n    return 1\n", encoding="utf-8")

    ran = driver.index_workspace(str(workspace))
    assert ran is True

    symbols = coding_module.storage.symbols_for_file(str(workspace / "main.py"))
    assert any(symbol.name == "entry" for symbol in symbols)