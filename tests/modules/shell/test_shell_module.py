"""
Unit tests for the Shell Module.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_registry.exceptions import (
    CapabilityNotFoundError,
)
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.module_manager import ModuleManager
from parika.core.module_manager.state import ModuleState
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_permission_manager import (
    WorkspacePermissionManager,
)
from parika.core.permission_manager.workspace_permission_scope import (
    WorkspacePermissionScope,
)
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.shell.driver import (
    MODULE_HEALTH_COMPONENT_ID,
    ShellModuleDriver,
)
from parika.modules.shell.manifest import SHELL_MODULE_ID, create_shell_module
from parika.tools.shell.manifest import SHELL_OPERATIONS


class _FakePrompt:
    def __init__(self, scope: WorkspacePermissionScope) -> None:
        self.scope = scope
        self.calls = 0

    def request_decision(self, *, workspace, operation, reason):  # noqa: ANN001
        self.calls += 1
        return self.scope


@pytest.fixture
def logger() -> Logger:
    return Logger(Configuration())


@pytest.fixture
def event_bus(logger: Logger) -> EventBus:
    return EventBus(logger=logger)


@pytest.fixture
def capability_registry(
    event_bus: EventBus, logger: Logger
) -> CapabilityRegistry:
    return CapabilityRegistry(event_bus=event_bus, logger=logger)


@pytest.fixture
def tool_manager(event_bus: EventBus, logger: Logger) -> ToolManager:
    return ToolManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def health_manager(event_bus: EventBus, logger: Logger) -> HealthManager:
    return HealthManager(event_bus=event_bus, logger=logger)


@pytest.fixture
def module_manager(event_bus: EventBus, logger: Logger) -> ModuleManager:
    return ModuleManager(
        configuration=Configuration(), event_bus=event_bus, logger=logger
    )


def _permissions(
    logger: Logger, event_bus: EventBus, *, trust_everything: bool = True
) -> WorkspacePermissionManager:
    permission_manager = PermissionManager(event_bus=event_bus, logger=logger)
    prompt = _FakePrompt(
        WorkspacePermissionScope.SESSION if trust_everything else WorkspacePermissionScope.DENY
    )
    return WorkspacePermissionManager(
        permission_manager=permission_manager,
        configuration=Configuration(),
        event_bus=event_bus,
        logger=logger,
        prompt=prompt,
    )


def _enabled_configuration(tmp_path: Path) -> Configuration:
    configuration = Configuration()
    configuration._config = {  # noqa: SLF001
        "shell": {"enabled": True},
        "workspace": {"default_workspace": str(tmp_path)},
    }
    return configuration


class TestModuleLifecycle:
    def test_load_registers_every_capability_and_tool(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        event_bus: EventBus,
        logger: Logger,
        tmp_path: Path,
    ) -> None:
        driver = ShellModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            permissions=_permissions(logger, event_bus),
            logger=logger,
            health_manager=health_manager,
            configuration=_enabled_configuration(tmp_path),
        )
        module_manager.register(create_shell_module(driver))
        module_manager.load(SHELL_MODULE_ID)

        for spec in SHELL_OPERATIONS:
            assert capability_registry.contains(spec.capability_id)
            assert tool_manager.contains(spec.tool_id)

        loaded = module_manager.get(SHELL_MODULE_ID)
        assert loaded.state is ModuleState.ACTIVE

    def test_load_registers_health_check(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        event_bus: EventBus,
        logger: Logger,
        tmp_path: Path,
    ) -> None:
        driver = ShellModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            permissions=_permissions(logger, event_bus),
            logger=logger,
            health_manager=health_manager,
            configuration=_enabled_configuration(tmp_path),
        )
        module_manager.register(create_shell_module(driver))
        module_manager.load(SHELL_MODULE_ID)

        assert health_manager.contains(MODULE_HEALTH_COMPONENT_ID)
        result = health_manager.run_check(MODULE_HEALTH_COMPONENT_ID)
        assert result.status is HealthStatus.HEALTHY

    def test_unload_unregisters_everything(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        event_bus: EventBus,
        logger: Logger,
        tmp_path: Path,
    ) -> None:
        driver = ShellModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            permissions=_permissions(logger, event_bus),
            logger=logger,
            health_manager=health_manager,
            configuration=_enabled_configuration(tmp_path),
        )
        module_manager.register(create_shell_module(driver))
        module_manager.load(SHELL_MODULE_ID)

        module_manager.unload(SHELL_MODULE_ID)

        for spec in SHELL_OPERATIONS:
            assert not capability_registry.contains(spec.capability_id)
            assert not tool_manager.contains(spec.tool_id)

        assert not health_manager.contains(MODULE_HEALTH_COMPONENT_ID)

        with pytest.raises(CapabilityNotFoundError):
            capability_registry.get(SHELL_OPERATIONS[0].capability_id)

    def test_disabled_by_configuration_never_registers(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        configuration = Configuration()
        configuration._config = {"shell": {"enabled": False}}  # noqa: SLF001

        driver = ShellModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            permissions=_permissions(logger, event_bus),
            logger=logger,
            configuration=configuration,
        )
        module_manager.register(create_shell_module(driver))
        module_manager.load(SHELL_MODULE_ID)

        for spec in SHELL_OPERATIONS:
            assert not capability_registry.contains(spec.capability_id)

        module_manager.unload(SHELL_MODULE_ID)


class TestToolExecutionThroughModule:
    def test_execute_via_tool_manager(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        event_bus: EventBus,
        logger: Logger,
        tmp_path: Path,
    ) -> None:
        driver = ShellModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            permissions=_permissions(logger, event_bus),
            logger=logger,
            configuration=_enabled_configuration(tmp_path),
        )
        module_manager.register(create_shell_module(driver))
        module_manager.load(SHELL_MODULE_ID)

        response = tool_manager.execute(
            "tool.shell_execute",
            ToolRequest(
                arguments={
                    "command": [sys.executable, "-c", "print('via module')"],
                    "cwd": str(tmp_path),
                }
            ),
        )

        assert response.result["exit_code"] == 0
        assert "via module" in response.result["stdout"]

    def test_execute_denied_by_workspace_permission_manager(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        event_bus: EventBus,
        logger: Logger,
        tmp_path: Path,
    ) -> None:
        driver = ShellModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            permissions=_permissions(logger, event_bus, trust_everything=False),
            logger=logger,
            configuration=_enabled_configuration(tmp_path),
        )
        module_manager.register(create_shell_module(driver))
        module_manager.load(SHELL_MODULE_ID)

        from parika.core.tool_manager.exceptions import ToolExecutionError

        with pytest.raises(ToolExecutionError):
            tool_manager.execute(
                "tool.shell_execute",
                ToolRequest(
                    arguments={
                        "command": [sys.executable, "-c", "pass"],
                        "cwd": str(tmp_path),
                    }
                ),
            )

    def test_background_processes_and_kill_share_one_registry(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        event_bus: EventBus,
        logger: Logger,
        tmp_path: Path,
    ) -> None:
        driver = ShellModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            permissions=_permissions(logger, event_bus),
            logger=logger,
            configuration=_enabled_configuration(tmp_path),
        )
        module_manager.register(create_shell_module(driver))
        module_manager.load(SHELL_MODULE_ID)

        spawned = tool_manager.execute(
            "tool.shell_background",
            ToolRequest(
                arguments={
                    "command": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(30)",
                    ],
                    "cwd": str(tmp_path),
                }
            ),
        )
        process_id = spawned.result["process_id"]

        listed = tool_manager.execute(
            "tool.shell_processes", ToolRequest(arguments={})
        )
        assert listed.attributes["count"] == 1

        killed = tool_manager.execute(
            "tool.shell_kill",
            ToolRequest(arguments={"process_id": process_id}),
        )
        assert killed.result["status"] == "killed"
