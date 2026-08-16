"""
Unit tests for the Filesystem Module.
"""

from __future__ import annotations

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
from parika.modules.filesystem.driver import (
    MODULE_HEALTH_COMPONENT_ID,
    FilesystemModuleDriver,
)
from parika.modules.filesystem.manifest import (
    FILESYSTEM_MODULE_ID,
    create_filesystem_module,
)
from parika.tools.filesystem.manifest import FILESYSTEM_OPERATIONS


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


def _configuration_with_root(root: str) -> Configuration:
    configuration = Configuration()
    configuration._config = {  # noqa: SLF001
        "filesystem": {
            "enabled": True,
            "allowed_roots": [root],
            "allow_write": True,
            "allow_delete": True,
        }
    }
    return configuration


class TestModuleLifecycle:
    def test_load_registers_every_capability_and_tool(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        logger: Logger,
        tmp_path,
    ) -> None:
        driver = FilesystemModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            health_manager=health_manager,
            configuration=_configuration_with_root(str(tmp_path)),
        )
        module = create_filesystem_module(driver)
        module_manager.register(module)
        module_manager.load(FILESYSTEM_MODULE_ID)

        for spec in FILESYSTEM_OPERATIONS:
            assert capability_registry.contains(spec.capability_id)
            assert tool_manager.contains(spec.tool_id)

        loaded = module_manager.get(FILESYSTEM_MODULE_ID)
        assert loaded.state is ModuleState.ACTIVE

    def test_load_registers_health_check(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        logger: Logger,
        tmp_path,
    ) -> None:
        driver = FilesystemModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            health_manager=health_manager,
            configuration=_configuration_with_root(str(tmp_path)),
        )
        module_manager.register(create_filesystem_module(driver))
        module_manager.load(FILESYSTEM_MODULE_ID)

        assert health_manager.contains(MODULE_HEALTH_COMPONENT_ID)
        result = health_manager.run_check(MODULE_HEALTH_COMPONENT_ID)
        assert result.status is HealthStatus.HEALTHY

    def test_unload_unregisters_everything(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        health_manager: HealthManager,
        logger: Logger,
        tmp_path,
    ) -> None:
        driver = FilesystemModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            health_manager=health_manager,
            configuration=_configuration_with_root(str(tmp_path)),
        )
        module_manager.register(create_filesystem_module(driver))
        module_manager.load(FILESYSTEM_MODULE_ID)

        module_manager.unload(FILESYSTEM_MODULE_ID)

        for spec in FILESYSTEM_OPERATIONS:
            assert not capability_registry.contains(spec.capability_id)
            assert not tool_manager.contains(spec.tool_id)

        assert not health_manager.contains(MODULE_HEALTH_COMPONENT_ID)

        with pytest.raises(CapabilityNotFoundError):
            capability_registry.get(FILESYSTEM_OPERATIONS[0].capability_id)

    def test_disabled_by_configuration_never_registers(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
    ) -> None:
        configuration = Configuration()
        configuration._config = {"filesystem": {"enabled": False}}  # noqa: SLF001

        driver = FilesystemModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
        )
        module_manager.register(create_filesystem_module(driver))
        module_manager.load(FILESYSTEM_MODULE_ID)

        for spec in FILESYSTEM_OPERATIONS:
            assert not capability_registry.contains(spec.capability_id)

        module_manager.unload(FILESYSTEM_MODULE_ID)


class TestToolExecutionThroughModule:
    def test_write_and_read_round_trip(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
        tmp_path,
    ) -> None:
        driver = FilesystemModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=_configuration_with_root(str(tmp_path)),
        )
        module_manager.register(create_filesystem_module(driver))
        module_manager.load(FILESYSTEM_MODULE_ID)

        target = str(tmp_path / "hello.txt")

        tool_manager.execute(
            "tool.filesystem_write",
            ToolRequest(arguments={"path": target, "content": "hi"}),
        )
        response = tool_manager.execute(
            "tool.filesystem_read", ToolRequest(arguments={"path": target})
        )

        assert response.result["content"] == "hi"

    def test_no_trusted_workspaces_denies_writes(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
        tmp_path,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"enabled": True, "trusted_workspaces": []},
            "workspace": {"default_workspace": ""},
        }
        driver = FilesystemModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
        )
        module_manager.register(create_filesystem_module(driver))
        module_manager.load(FILESYSTEM_MODULE_ID)

        from parika.core.tool_manager.exceptions import ToolExecutionError

        with pytest.raises(ToolExecutionError):
            tool_manager.execute(
                "tool.filesystem_write",
                ToolRequest(
                    arguments={"path": str(tmp_path / "x.txt"), "content": "x"}
                ),
            )


class _FakePrompt:
    def __init__(self, scope: WorkspacePermissionScope) -> None:
        self.scope = scope
        self.calls = 0

    def request_decision(self, *, workspace, operation, reason):  # noqa: ANN001
        self.calls += 1
        return self.scope


class TestWorkspacePermissionManagerIntegration:
    """
    End-to-end proof that a Filesystem write outside `trusted_workspaces`
    is delegated entirely to a real, shared `WorkspacePermissionManager`
    - not to any permission logic of the Filesystem Tool's own - all the
    way through `ToolManager.execute()`.
    """

    def test_write_outside_trusted_workspaces_is_delegated_and_authorized(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        event_bus: EventBus,
        logger: Logger,
        tmp_path,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"enabled": True, "trusted_workspaces": []},
            "workspace": {"default_workspace": ""},
        }
        permission_manager = PermissionManager(event_bus=event_bus, logger=logger)
        prompt = _FakePrompt(WorkspacePermissionScope.SESSION)
        workspace_permissions = WorkspacePermissionManager(
            permission_manager=permission_manager,
            configuration=configuration,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )

        driver = FilesystemModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
            permissions=workspace_permissions,
        )
        module_manager.register(create_filesystem_module(driver))
        module_manager.load(FILESYSTEM_MODULE_ID)

        target = str(tmp_path / "outside.txt")

        response = tool_manager.execute(
            "tool.filesystem_write",
            ToolRequest(arguments={"path": target, "content": "hi"}),
        )
        assert response.attributes["path"] == str(Path(target).resolve())
        assert prompt.calls == 1

        # A second write into the same workspace does not prompt again.
        tool_manager.execute(
            "tool.filesystem_write",
            ToolRequest(arguments={"path": target, "content": "hi again"}),
        )
        assert prompt.calls == 1

    def test_write_outside_trusted_workspaces_is_denied_without_a_prompt(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        event_bus: EventBus,
        logger: Logger,
        tmp_path,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"enabled": True, "trusted_workspaces": []},
            "workspace": {"default_workspace": ""},
        }
        permission_manager = PermissionManager(event_bus=event_bus, logger=logger)
        workspace_permissions = WorkspacePermissionManager(
            permission_manager=permission_manager,
            configuration=configuration,
            event_bus=event_bus,
            logger=logger,
            prompt=None,
        )

        driver = FilesystemModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
            permissions=workspace_permissions,
        )
        module_manager.register(create_filesystem_module(driver))
        module_manager.load(FILESYSTEM_MODULE_ID)

        from parika.core.tool_manager.exceptions import ToolExecutionError

        with pytest.raises(ToolExecutionError):
            tool_manager.execute(
                "tool.filesystem_write",
                ToolRequest(
                    arguments={
                        "path": str(tmp_path / "outside.txt"),
                        "content": "x",
                    }
                ),
            )

    def test_reads_succeed_even_with_no_configuration_at_all(
        self,
        module_manager: ModuleManager,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        logger: Logger,
        tmp_path,
    ) -> None:
        """
        Reads are always allowed, any resolvable host path,
        unconditionally - even for a Module constructed without any
        `Configuration` at all (see `security.PathSecurity`).
        """

        target = tmp_path / "readable.txt"
        target.write_text("hello")

        driver = FilesystemModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
        )
        module_manager.register(create_filesystem_module(driver))
        module_manager.load(FILESYSTEM_MODULE_ID)

        response = tool_manager.execute(
            "tool.filesystem_read",
            ToolRequest(arguments={"path": str(target)}),
        )

        assert response.result["content"] == "hello"
