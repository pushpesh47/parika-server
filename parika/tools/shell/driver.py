"""
PARIKA Shell Tool - Driver

Implements the `ToolDriver` contract
(`parika.core.tool_manager.driver.ToolDriver`) for every Shell Tool
operation.

A single `ShellToolDriver` instance is bound to exactly one
`ShellOperation` at construction time, mirroring
`FilesystemToolDriver` (see its module docstring for why one Tool per
capability is required here). The Shell Module constructs four
instances - one per operation - and registers each as its own Tool.

The Shell Tool never implements its own permission logic: before
running any command, every operation that spawns a process asks the
shared `WorkspacePermissionManager` whether `Execute` is authorized
for the command's working directory (see
`docs/architecture/Core_Component_Responsibilities.md` section 25).
It never parses a command string to infer or restrict filesystem
access - `Execute` permission authorizes only "a command may be run
with this directory as its working directory," nothing about what
that command does once running (see
`docs/development/Tool_Guide.md` section 22.2).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from parika.core.permission_manager.workspace_operation import WorkspaceOperation
from parika.core.permission_manager.workspace_permission_manager import (
    WorkspacePermissionManager,
)
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse

from .config import ShellToolConfig
from .exceptions import InvalidShellArgumentError, ShellPermissionDeniedError
from .manifest import ShellOperation
from .process_record import ShellProcessRecord
from .process_registry import ShellProcessRegistry


class ShellToolDriver:
    """
    ToolDriver implementing one Shell Tool operation.
    """

    def __init__(
        self,
        operation: ShellOperation,
        *,
        permissions: WorkspacePermissionManager,
        process_registry: ShellProcessRegistry,
        config: ShellToolConfig,
    ) -> None:
        """
        Initialize the driver for one operation.

        Args:
            operation:
                The single `ShellOperation` this driver instance
                implements.

            permissions:
                Shared `WorkspacePermissionManager` every operation
                that spawns a process asks before doing so. Required,
                not optional - the Shell Tool has no permission logic
                of its own to fall back to.

            process_registry:
                Shared `ShellProcessRegistry` every operation that
                spawns, lists, or kills a background process
                delegates to.

            config:
                Resolved `ShellToolConfig` snapshot.
        """

        self._operation = operation
        self._permissions = permissions
        self._process_registry = process_registry
        self._config = config

    def execute(self, request: ToolRequest) -> ToolResponse:
        """
        Execute this driver's bound operation.

        Raises:
            InvalidShellArgumentError:
                If a required argument is missing or invalid.

            ShellPermissionDeniedError:
                If `WorkspacePermissionManager` denies `Execute`
                permission for the command's working directory.

            ShellBackgroundLimitExceededError:
                If `shell.background` would exceed
                `[shell].max_background_processes`.

            UnknownProcessError:
                If `shell.processes`/`shell.kill` is given a
                `process_id` this Shell Tool never spawned.
        """

        match self._operation:
            case ShellOperation.EXECUTE:
                return self._execute_execute(request)
            case ShellOperation.BACKGROUND:
                return self._execute_background(request)
            case ShellOperation.PROCESSES:
                return self._execute_processes(request)
            case ShellOperation.KILL:
                return self._execute_kill(request)

        raise InvalidShellArgumentError(
            f"Unknown shell operation: {self._operation!r}."
        )

    def _execute_execute(self, request: ToolRequest) -> ToolResponse:
        command, use_shell = self._require_command(request)
        cwd = self._resolve_cwd(request)
        self._authorize_execute(cwd)

        timeout = min(
            float(
                request.arguments.get(
                    "timeout_seconds", self._config.default_timeout_seconds
                )
            ),
            self._config.max_timeout_seconds,
        )
        env = self._build_environment(request)

        try:
            completed = subprocess.run(  # noqa: S603
                command,
                cwd=str(cwd),
                env=env,
                timeout=timeout,
                capture_output=True,
                text=True,
                shell=use_shell,
            )

        except subprocess.TimeoutExpired as ex:
            return ToolResponse(
                result={
                    "stdout": _decode(ex.stdout),
                    "stderr": _decode(ex.stderr),
                    "exit_code": None,
                    "timed_out": True,
                },
                attributes={"cwd": str(cwd)},
            )

        return ToolResponse(
            result={
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "exit_code": completed.returncode,
                "timed_out": False,
            },
            attributes={"cwd": str(cwd)},
        )

    def _execute_background(self, request: ToolRequest) -> ToolResponse:
        command, use_shell = self._require_command(request)

        if use_shell:
            raise InvalidShellArgumentError(
                "request.arguments['command'] must be a list[str] argv "
                "for shell.background; a single shell string is not "
                "supported for background execution."
            )

        cwd = self._resolve_cwd(request)
        self._authorize_execute(cwd)
        env = self._build_environment(request)

        record = self._process_registry.spawn(command, cwd=cwd, env=env)

        return ToolResponse(
            result=_record_to_dict(record),
            attributes={"process_id": record.process_id},
        )

    def _execute_processes(self, request: ToolRequest) -> ToolResponse:
        raw_process_id = request.arguments.get("process_id")

        if raw_process_id is not None:
            process_id = self._require_process_id(raw_process_id)
            record = self._process_registry.get(process_id)

            return ToolResponse(
                result=_record_to_dict(record),
                attributes={"process_id": record.process_id},
            )

        records = self._process_registry.list_all()

        return ToolResponse(
            result=[_record_to_dict(record) for record in records],
            attributes={"count": len(records)},
        )

    def _execute_kill(self, request: ToolRequest) -> ToolResponse:
        process_id = self._require_process_id(request.arguments.get("process_id"))
        record = self._process_registry.kill(process_id)

        return ToolResponse(
            result=_record_to_dict(record),
            attributes={"process_id": record.process_id},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _authorize_execute(self, cwd: Path) -> None:
        decision = self._permissions.check(
            cwd, WorkspaceOperation.EXECUTE, reason="shell.execute"
        )

        if not decision.authorized:
            raise ShellPermissionDeniedError(
                f"Execution with working directory '{cwd}' was not "
                "authorized."
            )

    def _resolve_cwd(self, request: ToolRequest) -> Path:
        raw_cwd = request.arguments.get("cwd")

        if raw_cwd is None:
            if self._config.default_workspace is None:
                raise InvalidShellArgumentError(
                    "request.arguments['cwd'] is required (no "
                    "'[workspace].default_workspace' is configured)."
                )

            return self._config.default_workspace.resolve()

        if not isinstance(raw_cwd, str) or not raw_cwd.strip():
            raise InvalidShellArgumentError(
                "request.arguments['cwd'] must be a non-empty string."
            )

        return Path(raw_cwd).resolve()

    def _require_command(self, request: ToolRequest) -> tuple[Any, bool]:
        raw_command = request.arguments.get("command")

        if isinstance(raw_command, str):
            if not raw_command.strip():
                raise InvalidShellArgumentError(
                    "request.arguments['command'] must not be empty."
                )

            if not self._config.allow_shell_string:
                raise InvalidShellArgumentError(
                    "request.arguments['command'] as a single string "
                    "requires '[shell].allow_shell_string = true'; pass "
                    "a list[str] argv instead."
                )

            return raw_command, True

        if isinstance(raw_command, (list, tuple)):
            items = list(raw_command)

            if not items or not all(
                isinstance(item, str) and item for item in items
            ):
                raise InvalidShellArgumentError(
                    "request.arguments['command'] must be a non-empty "
                    "list of non-empty strings."
                )

            return items, False

        raise InvalidShellArgumentError(
            "request.arguments['command'] must be a list[str] (argv) "
            "or a string."
        )

    def _require_process_id(self, raw_process_id: object) -> str:
        if not isinstance(raw_process_id, str) or not raw_process_id.strip():
            raise InvalidShellArgumentError(
                "request.arguments['process_id'] must be a non-empty "
                "string."
            )

        return raw_process_id

    def _build_environment(self, request: ToolRequest) -> dict[str, str] | None:
        environment: dict[str, str] = (
            dict(os.environ) if self._config.inherit_environment else {}
        )

        extra_env = request.arguments.get("env")

        if isinstance(extra_env, dict):
            for key, value in extra_env.items():
                environment[str(key)] = str(value)

        return environment


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    return value


def _record_to_dict(record: ShellProcessRecord) -> dict[str, Any]:
    return {
        "process_id": record.process_id,
        "pid": record.pid,
        "command": list(record.command),
        "cwd": str(record.cwd),
        "status": record.status.value,
        "started_at": record.started_at.isoformat(),
        "exit_code": record.exit_code,
        "stdout_tail": record.stdout_tail,
        "stderr_tail": record.stderr_tail,
    }
