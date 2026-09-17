"""
PARIKA Autonomous Tool - Manifest

Defines the static Tool metadata for autonomous mission operations.
Follows the exact "one Tool per Capability" shape established by the
Filesystem/Shell Tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from parika.core.tool_manager.tool import Tool


AUTONOMOUS_TOOL_VERSION = "1.0.0"


class AutonomousOperation(StrEnum):
    """Every operation the Autonomous Tool implements, one per registered Capability."""
    GET_RESULT = "get_result"
    LIST_TASKS = "list_tasks"


@dataclass(frozen=True, slots=True, kw_only=True)
class AutonomousOperationSpec:
    """
    Everything needed to register one Autonomous Tool operation as its
    own Tool + Capability pair.
    """
    operation: AutonomousOperation
    capability_id: str
    tool_id: str
    name: str
    description: str
    tags: frozenset[str] = field(default_factory=frozenset)
    keywords: frozenset[str] = field(default_factory=frozenset)


AUTONOMOUS_OPERATIONS: tuple[AutonomousOperationSpec, ...] = (
    AutonomousOperationSpec(
        operation=AutonomousOperation.GET_RESULT,
        capability_id="mission.get_result",
        tool_id="tool.mission_get_result",
        name="Mission Get Result",
        description="Retrieves the status, result, and task details of a completed or running autonomous mission.",
        tags=frozenset({"autonomous", "mission", "result"}),
        keywords=frozenset({"mission", "result", "status", "autonomous", "get"}),
    ),
    AutonomousOperationSpec(
        operation=AutonomousOperation.LIST_TASKS,
        capability_id="mission.list_tasks",
        tool_id="tool.mission_list_tasks",
        name="Mission List Tasks",
        description="Lists all tasks belonging to an autonomous mission with their status and results.",
        tags=frozenset({"autonomous", "mission", "tasks", "list"}),
        keywords=frozenset({"mission", "tasks", "list", "autonomous", "progress"}),
    ),
)


def create_autonomous_tool(spec: AutonomousOperationSpec) -> Tool:
    """
    Build the immutable Tool descriptor for one Autonomous Tool operation.
    """
    return Tool(
        id=spec.tool_id,
        name=spec.name,
        version=AUTONOMOUS_TOOL_VERSION,
        description=spec.description,
        capabilities=(spec.capability_id,),
    )