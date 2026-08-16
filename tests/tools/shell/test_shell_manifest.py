"""
Unit tests for `parika.tools.shell.manifest`.
"""

from __future__ import annotations

from parika.tools.shell.manifest import (
    SHELL_OPERATIONS,
    ShellOperation,
    create_shell_tool,
)


class TestShellOperations:
    def test_every_operation_has_a_unique_capability_and_tool_id(self) -> None:
        capability_ids = {spec.capability_id for spec in SHELL_OPERATIONS}
        tool_ids = {spec.tool_id for spec in SHELL_OPERATIONS}

        assert len(capability_ids) == len(SHELL_OPERATIONS)
        assert len(tool_ids) == len(SHELL_OPERATIONS)

    def test_covers_every_shell_operation_enum_value(self) -> None:
        covered = {spec.operation for spec in SHELL_OPERATIONS}

        assert covered == set(ShellOperation)

    def test_capability_ids_are_namespaced_under_shell(self) -> None:
        for spec in SHELL_OPERATIONS:
            assert spec.capability_id.startswith("shell.")

    def test_tool_ids_are_namespaced_under_tool_shell(self) -> None:
        for spec in SHELL_OPERATIONS:
            assert spec.tool_id.startswith("tool.shell_")


class TestCreateShellTool:
    def test_creates_a_tool_bound_to_exactly_one_capability(self) -> None:
        spec = SHELL_OPERATIONS[0]
        tool = create_shell_tool(spec)

        assert tool.id == spec.tool_id
        assert tool.capabilities == (spec.capability_id,)
        assert tool.enabled is True
