"""
Unit tests for RepositoryIntelligenceModuleDriver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.registry import KnowledgeEngineRegistry
from parika.core.knowledge_manager.sqlite_storage import SqliteKnowledgeStorage
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.coding.driver import CodingModuleDriver
from parika.modules.repository_intelligence.driver import (
    RepositoryIntelligenceModuleDriver,
)


@pytest.fixture()
def knowledge_manager(tmp_path: Path, logger, event_bus) -> KnowledgeManager:
    storage = SqliteKnowledgeStorage(database_path=tmp_path / "knowledge.sqlite3")
    storage.initialize()
    return KnowledgeManager(
        storage=storage, registry=KnowledgeEngineRegistry(), event_bus=event_bus, logger=logger
    )


@pytest.fixture()
def coding_module(tmp_path: Path, logger, event_bus) -> CodingModuleDriver:
    capability_registry = CapabilityRegistry(event_bus, logger)
    tool_manager = ToolManager(event_bus, logger)
    driver = CodingModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        logger=logger,
        database_path=tmp_path / "coding_index.sqlite3",
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

    ran_again = driver.index_workspace(str(workspace))
    assert ran_again is False  # content unchanged -- skipped
