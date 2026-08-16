"""Unit tests for MemoryModuleDriver."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.memory_manager.memory_manager import MemoryManager
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.memory.driver import MemoryModuleDriver
from parika.tools.memory.manifest import (
    MEMORY_CAPABILITY_FORGET,
    MEMORY_CAPABILITY_REMEMBER,
    MEMORY_CAPABILITY_SEARCH,
    MEMORY_TOOL_ID_FORGET,
    MEMORY_TOOL_ID_REMEMBER,
    MEMORY_TOOL_ID_SEARCH,
)


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


class TestMemoryModuleDriver:
    def test_start_registers_capabilities_and_tools(
        self,
        memory_manager: MemoryManager,
        logger: Logger,
        event_bus: EventBus,
    ) -> None:
        capability_registry = CapabilityRegistry(event_bus=event_bus, logger=logger)
        tool_manager = ToolManager(event_bus=event_bus, logger=logger)

        driver = MemoryModuleDriver(
            memory_manager=memory_manager,
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
        )

        driver.start()

        assert capability_registry.contains(MEMORY_CAPABILITY_REMEMBER)
        assert capability_registry.contains(MEMORY_CAPABILITY_SEARCH)
        assert capability_registry.contains(MEMORY_CAPABILITY_FORGET)
        assert tool_manager.contains(MEMORY_TOOL_ID_REMEMBER)
        assert tool_manager.contains(MEMORY_TOOL_ID_SEARCH)
        assert tool_manager.contains(MEMORY_TOOL_ID_FORGET)

        driver.stop()

    def test_stop_unregisters_everything(
        self,
        memory_manager: MemoryManager,
        logger: Logger,
        event_bus: EventBus,
    ) -> None:
        capability_registry = CapabilityRegistry(event_bus=event_bus, logger=logger)
        tool_manager = ToolManager(event_bus=event_bus, logger=logger)

        driver = MemoryModuleDriver(
            memory_manager=memory_manager,
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
        )

        driver.start()
        driver.stop()

        assert not capability_registry.contains(MEMORY_CAPABILITY_REMEMBER)
        assert not tool_manager.contains(MEMORY_TOOL_ID_REMEMBER)

    def test_registered_tool_actually_calls_memory_manager(
        self,
        memory_manager: MemoryManager,
        logger: Logger,
        event_bus: EventBus,
    ) -> None:
        """
        End-to-end within the module: the registered `tool.
        memory_remember` Tool must actually persist through the
        injected MemoryManager, not fabricate a result.
        """

        capability_registry = CapabilityRegistry(event_bus=event_bus, logger=logger)
        tool_manager = ToolManager(event_bus=event_bus, logger=logger)

        driver = MemoryModuleDriver(
            memory_manager=memory_manager,
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
        )
        driver.start()

        response = tool_manager.execute(
            MEMORY_TOOL_ID_REMEMBER,
            ToolRequest(arguments={"content": "The user's name is Pushpesh."}),
        )

        assert response.result["stored"] is True
        assert memory_manager.count() == 1

        driver.stop()

    def test_health_check_reports_healthy(
        self,
        memory_manager: MemoryManager,
        logger: Logger,
        event_bus: EventBus,
    ) -> None:
        capability_registry = CapabilityRegistry(event_bus=event_bus, logger=logger)
        tool_manager = ToolManager(event_bus=event_bus, logger=logger)

        driver = MemoryModuleDriver(
            memory_manager=memory_manager,
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
        )

        result = driver._check_health()

        assert result.status.name == "HEALTHY"
