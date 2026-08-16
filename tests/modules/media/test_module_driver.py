"""
Unit tests for `MediaModuleDriver`'s registration lifecycle, mirroring
`tests/modules/expense/test_expense_module.py`'s own shape.
"""

from __future__ import annotations

import pytest

from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.media.module_driver import MODULE_HEALTH_COMPONENT_ID, MediaModuleDriver
from parika.tools.media.config import MediaToolConfig
from parika.tools.media.connection_registry import MediaConnectionRegistry
from parika.tools.media.manifest import OPERATION_CAPABILITY_ID, OPERATION_TOOL_ID, MediaOperation
from parika.tools.media.resolution import MediaResolver
from parika.tools.media.security import LocalMediaPathSecurity, LocalMediaPathSecurityConfig
from parika.tools.media.state_store import MediaStateStore


@pytest.fixture
def capability_registry(event_bus, logger) -> CapabilityRegistry:
    return CapabilityRegistry(event_bus=event_bus, logger=logger)


@pytest.fixture
def tool_manager(event_bus, logger) -> ToolManager:
    return ToolManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def health_manager(event_bus, logger) -> HealthManager:
    return HealthManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def resolver() -> MediaResolver:
    return MediaResolver(
        path_security=LocalMediaPathSecurity(LocalMediaPathSecurityConfig()), brain=None
    )


def _driver(
    capability_registry: CapabilityRegistry,
    tool_manager: ToolManager,
    logger,
    *,
    resolver: MediaResolver,
    health_manager: HealthManager | None = None,
    config: MediaToolConfig | None = None,
) -> MediaModuleDriver:
    return MediaModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        state_store=MediaStateStore(),
        dispatcher=MediaConnectionRegistry(),
        resolver=resolver,
        config=config or MediaToolConfig(),
        logger=logger,
        health_manager=health_manager,
    )


class TestModuleLifecycle:
    def test_start_registers_every_capability_and_tool(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger,
        resolver: MediaResolver,
    ) -> None:
        driver = _driver(capability_registry, tool_manager, logger, resolver=resolver)
        driver.start()

        for operation in MediaOperation:
            capability_id = OPERATION_CAPABILITY_ID[operation]
            tool_id = OPERATION_TOOL_ID[operation]

            assert capability_registry.contains(capability_id)
            assert tool_manager.contains(tool_id)

            definition = capability_registry.get(capability_id)
            assert definition.category is CapabilityCategory.TOOL
            assert "tool_affordance" in definition.metadata

        driver.stop()

    def test_stop_unregisters_everything(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger,
        resolver: MediaResolver,
    ) -> None:
        driver = _driver(capability_registry, tool_manager, logger, resolver=resolver)
        driver.start()
        driver.stop()

        for operation in MediaOperation:
            assert not capability_registry.contains(OPERATION_CAPABILITY_ID[operation])
            assert not tool_manager.contains(OPERATION_TOOL_ID[operation])

    def test_exact_thirteen_operations_registered(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger,
        resolver: MediaResolver,
    ) -> None:
        driver = _driver(capability_registry, tool_manager, logger, resolver=resolver)
        driver.start()

        assert len(list(MediaOperation)) == 13
        assert len(capability_registry.get_by_tag("media")) == 13

        driver.stop()

    def test_disabled_by_configuration_registers_nothing(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger,
        resolver: MediaResolver,
    ) -> None:
        driver = _driver(
            capability_registry,
            tool_manager,
            logger,
            resolver=resolver,
            config=MediaToolConfig(enabled=False),
        )
        driver.start()

        for operation in MediaOperation:
            assert not capability_registry.contains(OPERATION_CAPABILITY_ID[operation])

        driver.stop()  # must not raise even though nothing was registered

    def test_registers_and_unregisters_a_health_check(
        self,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        logger,
        resolver: MediaResolver,
    ) -> None:
        driver = _driver(
            capability_registry,
            tool_manager,
            logger,
            resolver=resolver,
            health_manager=health_manager,
        )
        driver.start()

        assert health_manager.contains(MODULE_HEALTH_COMPONENT_ID)
        result = health_manager.run_check(MODULE_HEALTH_COMPONENT_ID)
        assert result.status is HealthStatus.HEALTHY

        driver.stop()

        assert not health_manager.contains(MODULE_HEALTH_COMPONENT_ID)
