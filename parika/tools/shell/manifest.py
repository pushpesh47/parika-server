"""
PARIKA Shell Tool - Manifest

Defines the static Tool metadata describing every Shell Tool
operation.

Like the Filesystem Tool (see
`parika/tools/filesystem/manifest.py`'s module docstring for the full
rationale), the Shell Tool implements four distinct Capabilities
(`shell.execute`, `shell.background`, `shell.processes`, `shell.kill`)
and therefore follows the same "one Tool per Capability" shape: the
Shell Module registers **one Tool per capability**, each with its own
`tool.shell_<operation>` identifier and its own `ShellToolDriver`
instance bound to that one operation. This requires no change to
Planner, CapabilityResolver, CapabilityExecutor, or ToolManager.

This module owns Tool creation. ToolManager only registers and stores
the Tool instances produced here; it does not create Tool objects
itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from parika.core.tool_manager.tool import Tool

SHELL_TOOL_VERSION = "1.0.0"


class ShellOperation(StrEnum):
    """
    Every operation the Shell Tool implements, one per registered
    Capability.
    """

    EXECUTE = "execute"
    BACKGROUND = "background"
    PROCESSES = "processes"
    KILL = "kill"


@dataclass(frozen=True, slots=True, kw_only=True)
class ShellOperationSpec:
    """
    Everything needed to register one Shell Tool operation as its own
    Tool + Capability pair.
    """

    operation: ShellOperation
    capability_id: str
    tool_id: str
    name: str
    description: str


SHELL_OPERATIONS: tuple[ShellOperationSpec, ...] = (
    ShellOperationSpec(
        operation=ShellOperation.EXECUTE,
        capability_id="shell.execute",
        tool_id="tool.shell_execute",
        name="Shell Execute",
        description=(
            "Runs a command to completion, capturing stdout, stderr, "
            "and the exit code, subject to a timeout."
        ),
    ),
    ShellOperationSpec(
        operation=ShellOperation.BACKGROUND,
        capability_id="shell.background",
        tool_id="tool.shell_background",
        name="Shell Background",
        description=(
            "Starts a command detached and returns a process id "
            "immediately."
        ),
    ),
    ShellOperationSpec(
        operation=ShellOperation.PROCESSES,
        capability_id="shell.processes",
        tool_id="tool.shell_processes",
        name="Shell Processes",
        description=(
            "Lists or inspects tracked background processes and their "
            "captured output."
        ),
    ),
    ShellOperationSpec(
        operation=ShellOperation.KILL,
        capability_id="shell.kill",
        tool_id="tool.shell_kill",
        name="Shell Kill",
        description="Terminates a tracked background process.",
    ),
)
"""
Every Shell Tool operation PARIKA implements, in the order the Shell
Module registers them. Adding a future operation means appending one
entry here and one handler in `driver.py` - no other module needs to
change.
"""


def create_shell_tool(spec: ShellOperationSpec) -> Tool:
    """
    Build the immutable Tool descriptor for one Shell Tool operation.

    Args:
        spec:
            The operation's registration spec (see `SHELL_OPERATIONS`).

    Returns:
        A Tool ready to be registered with ToolManager alongside a
        `ShellToolDriver` bound to `spec.operation`.
    """

    return Tool(
        id=spec.tool_id,
        name=spec.name,
        version=SHELL_TOOL_VERSION,
        description=spec.description,
        capabilities=(spec.capability_id,),
    )
