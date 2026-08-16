"""
Unit tests for ShellToolDriver.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from parika.core.permission_manager.workspace_operation import WorkspaceOperation
from parika.core.permission_manager.workspace_permission_decision import (
    WorkspacePermissionDecision,
)
from parika.core.tool_manager.request import ToolRequest
from parika.tools.shell.config import ShellToolConfig
from parika.tools.shell.driver import ShellToolDriver
from parika.tools.shell.exceptions import (
    InvalidShellArgumentError,
    ShellPermissionDeniedError,
)
from parika.tools.shell.manifest import ShellOperation
from parika.tools.shell.process_record import ShellProcessStatus
from parika.tools.shell.process_registry import ShellProcessRegistry


class _FakeLogger:
    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


class _FakePermissions:
    def __init__(self, *, authorized: bool) -> None:
        self.authorized = authorized
        self.calls: list[tuple[Path, WorkspaceOperation, str | None]] = []

    def check(
        self,
        path: Path,
        operation: WorkspaceOperation,
        *,
        reason: str | None = None,
    ) -> WorkspacePermissionDecision:
        self.calls.append((path, operation, reason))

        return WorkspacePermissionDecision(
            workspace=path,
            operation=operation,
            authorized=self.authorized,
        )


def _config(**overrides: Any) -> ShellToolConfig:
    return ShellToolConfig(**overrides)


def _registry() -> ShellProcessRegistry:
    return ShellProcessRegistry(
        logger=_FakeLogger(),  # type: ignore[arg-type]
        output_buffer_max_bytes=65536,
        max_background_processes=20,
        kill_grace_period_seconds=2.0,
    )


def _wait_until_not_running(
    registry: ShellProcessRegistry, process_id: str, *, timeout: float = 5.0
) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if registry.get(process_id).status is not ShellProcessStatus.RUNNING:
            return

        time.sleep(0.02)

    raise AssertionError(f"Process '{process_id}' did not finish within {timeout}s.")


class TestExecute:
    def test_authorized_execute_returns_output_and_exit_code(
        self, tmp_path: Path
    ) -> None:
        permissions = _FakePermissions(authorized=True)
        driver = ShellToolDriver(
            ShellOperation.EXECUTE,
            permissions=permissions,
            process_registry=_registry(),
            config=_config(enabled=True),
        )

        response = driver.execute(
            ToolRequest(
                arguments={
                    "command": [sys.executable, "-c", "print('hi')"],
                    "cwd": str(tmp_path),
                }
            )
        )

        assert response.result["exit_code"] == 0
        assert "hi" in response.result["stdout"]
        assert response.result["timed_out"] is False

    def test_execute_asks_workspace_permission_manager_for_execute(
        self, tmp_path: Path
    ) -> None:
        permissions = _FakePermissions(authorized=True)
        driver = ShellToolDriver(
            ShellOperation.EXECUTE,
            permissions=permissions,
            process_registry=_registry(),
            config=_config(enabled=True),
        )

        driver.execute(
            ToolRequest(
                arguments={
                    "command": [sys.executable, "-c", "pass"],
                    "cwd": str(tmp_path),
                }
            )
        )

        assert permissions.calls == [
            (tmp_path.resolve(), WorkspaceOperation.EXECUTE, "shell.execute")
        ]

    def test_denied_permission_raises_and_never_runs_the_command(
        self, tmp_path: Path
    ) -> None:
        permissions = _FakePermissions(authorized=False)
        driver = ShellToolDriver(
            ShellOperation.EXECUTE,
            permissions=permissions,
            process_registry=_registry(),
            config=_config(enabled=True),
        )
        marker = tmp_path / "should_not_exist.txt"

        with pytest.raises(ShellPermissionDeniedError):
            driver.execute(
                ToolRequest(
                    arguments={
                        "command": [
                            sys.executable,
                            "-c",
                            f"open(r'{marker}', 'w').close()",
                        ],
                        "cwd": str(tmp_path),
                    }
                )
            )

        assert not marker.exists()

    def test_missing_command_raises(self, tmp_path: Path) -> None:
        driver = ShellToolDriver(
            ShellOperation.EXECUTE,
            permissions=_FakePermissions(authorized=True),
            process_registry=_registry(),
            config=_config(enabled=True),
        )

        with pytest.raises(InvalidShellArgumentError):
            driver.execute(ToolRequest(arguments={"cwd": str(tmp_path)}))

    def test_string_command_rejected_by_default(self, tmp_path: Path) -> None:
        driver = ShellToolDriver(
            ShellOperation.EXECUTE,
            permissions=_FakePermissions(authorized=True),
            process_registry=_registry(),
            config=_config(enabled=True, allow_shell_string=False),
        )

        with pytest.raises(InvalidShellArgumentError):
            driver.execute(
                ToolRequest(
                    arguments={"command": "echo hi", "cwd": str(tmp_path)}
                )
            )

    def test_string_command_allowed_when_opted_in(self, tmp_path: Path) -> None:
        driver = ShellToolDriver(
            ShellOperation.EXECUTE,
            permissions=_FakePermissions(authorized=True),
            process_registry=_registry(),
            config=_config(enabled=True, allow_shell_string=True),
        )

        response = driver.execute(
            ToolRequest(
                arguments={
                    "command": f"{sys.executable} -c \"print('shelled')\"",
                    "cwd": str(tmp_path),
                }
            )
        )

        assert "shelled" in response.result["stdout"]

    def test_timeout_is_reported_not_raised(self, tmp_path: Path) -> None:
        driver = ShellToolDriver(
            ShellOperation.EXECUTE,
            permissions=_FakePermissions(authorized=True),
            process_registry=_registry(),
            config=_config(enabled=True),
        )

        response = driver.execute(
            ToolRequest(
                arguments={
                    "command": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(5)",
                    ],
                    "cwd": str(tmp_path),
                    "timeout_seconds": 0.2,
                }
            )
        )

        assert response.result["timed_out"] is True
        assert response.result["exit_code"] is None

    def test_timeout_is_clamped_to_configured_ceiling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        driver = ShellToolDriver(
            ShellOperation.EXECUTE,
            permissions=_FakePermissions(authorized=True),
            process_registry=_registry(),
            config=_config(enabled=True, max_timeout_seconds=0.2),
        )

        captured: dict[str, float] = {}

        import parika.tools.shell.driver as driver_module

        original_run = driver_module.subprocess.run

        def _fake_run(*args: Any, **kwargs: Any):  # noqa: ANN002, ANN003
            captured["timeout"] = kwargs["timeout"]
            return original_run(
                [sys.executable, "-c", "pass"], capture_output=True, text=True
            )

        monkeypatch.setattr(driver_module.subprocess, "run", _fake_run)

        driver.execute(
            ToolRequest(
                arguments={
                    "command": [sys.executable, "-c", "pass"],
                    "cwd": str(tmp_path),
                    "timeout_seconds": 999,
                }
            )
        )

        assert captured["timeout"] == 0.2

    def test_cwd_defaults_to_configured_default_workspace(
        self, tmp_path: Path
    ) -> None:
        permissions = _FakePermissions(authorized=True)
        driver = ShellToolDriver(
            ShellOperation.EXECUTE,
            permissions=permissions,
            process_registry=_registry(),
            config=_config(enabled=True, default_workspace=tmp_path),
        )

        driver.execute(
            ToolRequest(arguments={"command": [sys.executable, "-c", "pass"]})
        )

        assert permissions.calls[0][0] == tmp_path.resolve()

    def test_missing_cwd_and_no_default_workspace_raises(self) -> None:
        driver = ShellToolDriver(
            ShellOperation.EXECUTE,
            permissions=_FakePermissions(authorized=True),
            process_registry=_registry(),
            config=_config(enabled=True, default_workspace=None),
        )

        with pytest.raises(InvalidShellArgumentError):
            driver.execute(
                ToolRequest(
                    arguments={"command": [sys.executable, "-c", "pass"]}
                )
            )


class TestBackground:
    def test_background_spawns_and_returns_process_id(
        self, tmp_path: Path
    ) -> None:
        registry = _registry()
        driver = ShellToolDriver(
            ShellOperation.BACKGROUND,
            permissions=_FakePermissions(authorized=True),
            process_registry=registry,
            config=_config(enabled=True),
        )

        response = driver.execute(
            ToolRequest(
                arguments={
                    "command": [sys.executable, "-c", "print('bg')"],
                    "cwd": str(tmp_path),
                }
            )
        )

        process_id = response.result["process_id"]
        _wait_until_not_running(registry, process_id)
        assert "bg" in registry.get(process_id).stdout_tail

    def test_background_denied_by_permissions_never_spawns(
        self, tmp_path: Path
    ) -> None:
        registry = _registry()
        driver = ShellToolDriver(
            ShellOperation.BACKGROUND,
            permissions=_FakePermissions(authorized=False),
            process_registry=registry,
            config=_config(enabled=True),
        )

        with pytest.raises(ShellPermissionDeniedError):
            driver.execute(
                ToolRequest(
                    arguments={
                        "command": [sys.executable, "-c", "pass"],
                        "cwd": str(tmp_path),
                    }
                )
            )

        assert registry.list_all() == ()

    def test_background_rejects_string_command(self, tmp_path: Path) -> None:
        driver = ShellToolDriver(
            ShellOperation.BACKGROUND,
            permissions=_FakePermissions(authorized=True),
            process_registry=_registry(),
            config=_config(enabled=True, allow_shell_string=True),
        )

        with pytest.raises(InvalidShellArgumentError):
            driver.execute(
                ToolRequest(
                    arguments={"command": "echo hi", "cwd": str(tmp_path)}
                )
            )


class TestProcesses:
    def test_lists_every_tracked_process(self, tmp_path: Path) -> None:
        registry = _registry()
        background_driver = ShellToolDriver(
            ShellOperation.BACKGROUND,
            permissions=_FakePermissions(authorized=True),
            process_registry=registry,
            config=_config(enabled=True),
        )
        processes_driver = ShellToolDriver(
            ShellOperation.PROCESSES,
            permissions=_FakePermissions(authorized=True),
            process_registry=registry,
            config=_config(enabled=True),
        )

        background_driver.execute(
            ToolRequest(
                arguments={
                    "command": [sys.executable, "-c", "pass"],
                    "cwd": str(tmp_path),
                }
            )
        )

        response = processes_driver.execute(ToolRequest(arguments={}))

        assert response.attributes["count"] == 1

    def test_inspects_one_process_by_id(self, tmp_path: Path) -> None:
        registry = _registry()
        background_driver = ShellToolDriver(
            ShellOperation.BACKGROUND,
            permissions=_FakePermissions(authorized=True),
            process_registry=registry,
            config=_config(enabled=True),
        )
        processes_driver = ShellToolDriver(
            ShellOperation.PROCESSES,
            permissions=_FakePermissions(authorized=True),
            process_registry=registry,
            config=_config(enabled=True),
        )

        spawned = background_driver.execute(
            ToolRequest(
                arguments={
                    "command": [sys.executable, "-c", "pass"],
                    "cwd": str(tmp_path),
                }
            )
        )
        process_id = spawned.result["process_id"]

        response = processes_driver.execute(
            ToolRequest(arguments={"process_id": process_id})
        )

        assert response.result["process_id"] == process_id

    def test_does_not_ask_permissions_at_all(self, tmp_path: Path) -> None:
        permissions = _FakePermissions(authorized=True)
        driver = ShellToolDriver(
            ShellOperation.PROCESSES,
            permissions=permissions,
            process_registry=_registry(),
            config=_config(enabled=True),
        )

        driver.execute(ToolRequest(arguments={}))

        assert permissions.calls == []


class TestKill:
    def test_kills_a_tracked_process(self, tmp_path: Path) -> None:
        registry = _registry()
        background_driver = ShellToolDriver(
            ShellOperation.BACKGROUND,
            permissions=_FakePermissions(authorized=True),
            process_registry=registry,
            config=_config(enabled=True),
        )
        kill_driver = ShellToolDriver(
            ShellOperation.KILL,
            permissions=_FakePermissions(authorized=True),
            process_registry=registry,
            config=_config(enabled=True),
        )

        spawned = background_driver.execute(
            ToolRequest(
                arguments={
                    "command": [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(30)",
                    ],
                    "cwd": str(tmp_path),
                }
            )
        )
        process_id = spawned.result["process_id"]

        response = kill_driver.execute(
            ToolRequest(arguments={"process_id": process_id})
        )

        assert response.result["status"] == "killed"

    def test_missing_process_id_raises(self) -> None:
        driver = ShellToolDriver(
            ShellOperation.KILL,
            permissions=_FakePermissions(authorized=True),
            process_registry=_registry(),
            config=_config(enabled=True),
        )

        with pytest.raises(InvalidShellArgumentError):
            driver.execute(ToolRequest(arguments={}))
