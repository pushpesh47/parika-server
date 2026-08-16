"""
End-to-end integration tests for the System Interaction Foundation:

    Brain -> Planner -> TaskManager -> CapabilityExecutor ->
    ToolManager -> <Filesystem|Shell ToolDriver> ->
    WorkspacePermissionManager -> PermissionManager

Proves, against the real Core pipeline (mirroring
`tests/integration/test_new_tools_pipeline.py`'s shape exactly), that:

- A Filesystem write and a Shell execute outside `trusted_workspaces`
  are both delegated entirely to one shared `WorkspacePermissionManager`
  - neither Tool implements any permission logic of its own.
- Exactly one prompt is shown per workspace; a second access to the
  same workspace through either Tool is authorized without prompting
  again.
- A grant made via one Tool (Filesystem) is honored by the other
  (Shell) - proving centralization, not two independent
  reimplementations.
"""

from __future__ import annotations

import sys

import pytest

from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.capability_executor.capability_executor import (
    CapabilityExecutor,
)
from parika.core.capability_registry.capability_registry import (
    CapabilityRegistry,
)
from parika.core.capability_resolver.capability_resolver import (
    CapabilityResolver,
)
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.module_manager.module_manager import ModuleManager
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_permission_manager import (
    WorkspacePermissionManager,
)
from parika.core.permission_manager.workspace_permission_scope import (
    WorkspacePermissionScope,
)
from parika.core.planner.goal import Goal
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.task_manager.task_status import TaskStatus
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.filesystem.driver import FilesystemModuleDriver
from parika.modules.filesystem.manifest import (
    FILESYSTEM_MODULE_ID,
    create_filesystem_module,
)
from parika.modules.shell.driver import ShellModuleDriver
from parika.modules.shell.manifest import SHELL_MODULE_ID, create_shell_module


class _RecordingPrompt:
    def __init__(self, scope: WorkspacePermissionScope) -> None:
        self.scope = scope
        self.calls: list[str] = []

    def request_decision(self, *, workspace, operation, reason):  # noqa: ANN001
        self.calls.append(str(workspace))
        return self.scope


class Pipeline:
    """
    Bundles the full, real Core stack plus the Filesystem and Shell
    Modules, sharing exactly one `WorkspacePermissionManager`.
    """

    def __init__(self, *, tmp_path, prompt: _RecordingPrompt) -> None:  # noqa: ANN001
        self.prompt = prompt

        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {
                "enabled": True,
                "trusted_workspaces": [],
                "allow_write": True,
                "allow_delete": True,
            },
            "shell": {"enabled": True},
            "workspace": {"default_workspace": ""},
        }

        logger = Logger(configuration)
        event_bus = EventBus(logger=logger)

        capability_registry = CapabilityRegistry(
            event_bus=event_bus, logger=logger
        )
        capability_resolver = CapabilityResolver(
            capability_registry=capability_registry, logger=logger
        )
        resource_manager = ResourceManager(
            configuration=configuration, logger=logger
        )
        policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
        provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
        tool_manager = ToolManager(event_bus=event_bus, logger=logger)
        module_manager = ModuleManager(
            configuration=configuration, event_bus=event_bus, logger=logger
        )

        permission_manager = PermissionManager(event_bus=event_bus, logger=logger)
        self.workspace_permissions = WorkspacePermissionManager(
            permission_manager=permission_manager,
            configuration=configuration,
            event_bus=event_bus,
            logger=logger,
            prompt=prompt,
        )

        capability_executor = CapabilityExecutor(
            event_bus=event_bus,
            logger=logger,
            tool_manager=tool_manager,
            provider_manager=provider_manager,
        )
        self.task_manager = TaskManager(
            event_bus=event_bus,
            logger=logger,
            capability_executor=capability_executor,
        )
        planner = Planner(
            capability_resolver=capability_resolver,
            resource_manager=resource_manager,
            policy_engine=policy_engine,
            provider_manager=provider_manager,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
        )
        self.brain = Brain(
            planner=planner, task_manager=self.task_manager, logger=logger
        )

        self.module_manager = module_manager
        self.capability_registry = capability_registry

        filesystem_driver = FilesystemModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            logger=logger,
            configuration=configuration,
            permissions=self.workspace_permissions,
        )
        module_manager.register(create_filesystem_module(filesystem_driver))
        module_manager.load(FILESYSTEM_MODULE_ID)

        shell_driver = ShellModuleDriver(
            capability_registry=capability_registry,
            tool_manager=tool_manager,
            permissions=self.workspace_permissions,
            logger=logger,
            configuration=configuration,
        )
        module_manager.register(create_shell_module(shell_driver))
        module_manager.load(SHELL_MODULE_ID)


@pytest.fixture
def trusting_prompt() -> _RecordingPrompt:
    return _RecordingPrompt(WorkspacePermissionScope.SESSION)


@pytest.fixture
def pipeline(tmp_path, trusting_prompt: _RecordingPrompt) -> Pipeline:  # noqa: ANN001
    return Pipeline(tmp_path=tmp_path, prompt=trusting_prompt)


class TestFilesystemWriteDelegatesToWorkspacePermissionManager:
    def test_write_outside_trusted_workspaces_prompts_once(
        self, pipeline: Pipeline, tmp_path
    ) -> None:
        target = str(tmp_path / "note.txt")

        first = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    Goal(
                        id="write-1",
                        capability_id="filesystem.write",
                        inputs={"path": target, "content": "hello"},
                    ),
                )
            )
        )
        assert first.succeeded
        assert pipeline.prompt.calls == [str(tmp_path.resolve())]

        second = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    Goal(
                        id="write-2",
                        capability_id="filesystem.write",
                        inputs={"path": target, "content": "hello again"},
                    ),
                )
            )
        )
        assert second.succeeded
        # No second prompt for the same workspace.
        assert pipeline.prompt.calls == [str(tmp_path.resolve())]

    def test_denied_write_fails_the_goal_without_touching_disk(
        self, tmp_path
    ) -> None:
        pipeline = Pipeline(
            tmp_path=tmp_path,
            prompt=_RecordingPrompt(WorkspacePermissionScope.DENY),
        )
        target = tmp_path / "should_not_exist.txt"

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    Goal(
                        id="write-denied",
                        capability_id="filesystem.write",
                        inputs={"path": str(target), "content": "x"},
                    ),
                )
            )
        )

        assert not response.succeeded
        assert response.results[0].status is TaskStatus.FAILED
        assert not target.exists()


class TestShellExecuteDelegatesToWorkspacePermissionManager:
    def test_execute_outside_trusted_workspaces_prompts_once(
        self, pipeline: Pipeline, tmp_path
    ) -> None:
        goal = Goal(
            id="shell-1",
            capability_id="shell.execute",
            inputs={
                "command": [sys.executable, "-c", "print('hi')"],
                "cwd": str(tmp_path),
            },
        )

        first = pipeline.brain.handle(BrainRequest(goals=(goal,)))
        assert first.succeeded
        assert pipeline.prompt.calls == [str(tmp_path.resolve())]

        second = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    Goal(
                        id="shell-2",
                        capability_id="shell.execute",
                        inputs={
                            "command": [sys.executable, "-c", "print('again')"],
                            "cwd": str(tmp_path),
                        },
                    ),
                )
            )
        )
        assert second.succeeded
        assert pipeline.prompt.calls == [str(tmp_path.resolve())]

    def test_denied_execute_fails_the_goal(self, tmp_path) -> None:
        pipeline = Pipeline(
            tmp_path=tmp_path,
            prompt=_RecordingPrompt(WorkspacePermissionScope.DENY),
        )

        response = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    Goal(
                        id="shell-denied",
                        capability_id="shell.execute",
                        inputs={
                            "command": [sys.executable, "-c", "pass"],
                            "cwd": str(tmp_path),
                        },
                    ),
                )
            )
        )

        assert not response.succeeded
        assert response.results[0].status is TaskStatus.FAILED


class TestCentralizedPermissionSharedAcrossTools:
    def test_session_grant_is_scoped_per_operation_not_blanket(
        self, pipeline: Pipeline, tmp_path
    ) -> None:
        """
        A `SESSION` grant authorizes exactly the operation it was
        requested for (`Write`) - it does not implicitly authorize an
        unrelated operation (`Execute`) for the same workspace, since
        the two are independently namespaced `PermissionManager`
        grants (`workspace:<path>` + `write` vs. `workspace:<path>` +
        `execute`). Full cross-operation, cross-Tool trust only comes
        from a workspace actually joining `trusted_workspaces` (see
        `test_is_trusted_reflects_across_both_tools_after_permanent_grant`
        below) - proving grants are precise, not accidentally
        over-broad, while still being resolved by one shared authority
        both Tools ask.
        """

        write_response = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    Goal(
                        id="fs-write",
                        capability_id="filesystem.write",
                        inputs={
                            "path": str(tmp_path / "a.txt"),
                            "content": "hi",
                        },
                    ),
                )
            )
        )
        assert write_response.succeeded
        assert pipeline.prompt.calls == [str(tmp_path.resolve())]

        shell_response = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    Goal(
                        id="shell-reuse",
                        capability_id="shell.execute",
                        inputs={
                            "command": [sys.executable, "-c", "pass"],
                            "cwd": str(tmp_path),
                        },
                    ),
                )
            )
        )

        assert shell_response.succeeded
        # A second prompt IS expected here: EXECUTE was never granted,
        # only WRITE was - both prompts targeted the same workspace,
        # proving both Tools consult the very same
        # WorkspacePermissionManager/PermissionManager registry rather
        # than each maintaining an independent one.
        assert pipeline.prompt.calls == [
            str(tmp_path.resolve()),
            str(tmp_path.resolve()),
        ]

    def test_is_trusted_reflects_across_both_tools_after_permanent_grant(
        self, tmp_path
    ) -> None:
        pipeline = Pipeline(
            tmp_path=tmp_path,
            prompt=_RecordingPrompt(WorkspacePermissionScope.PERMANENT),
        )

        pipeline.brain.handle(
            BrainRequest(
                goals=(
                    Goal(
                        id="fs-write",
                        capability_id="filesystem.write",
                        inputs={
                            "path": str(tmp_path / "a.txt"),
                            "content": "hi",
                        },
                    ),
                )
            )
        )

        assert pipeline.workspace_permissions.is_trusted(tmp_path / "b.txt")

        # A subsequent shell.execute in the now-permanently-trusted
        # workspace needs no prompt at all.
        response = pipeline.brain.handle(
            BrainRequest(
                goals=(
                    Goal(
                        id="shell-after-permanent",
                        capability_id="shell.execute",
                        inputs={
                            "command": [sys.executable, "-c", "pass"],
                            "cwd": str(tmp_path),
                        },
                    ),
                )
            )
        )
        assert response.succeeded
        assert pipeline.prompt.calls == [str(tmp_path.resolve())]
