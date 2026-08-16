"""
PARIKA Filesystem Tool - Manifest

Defines the static Tool metadata describing every Filesystem Tool
operation.

Unlike the Runtime Info and Web Search Tools - which each implement
exactly one Capability - the Filesystem Tool implements twelve
distinct Capabilities (`filesystem.read`, `filesystem.write`, ...).
`ToolRequest` carries no capability identifier (see
`parika/core/tool_manager/request.py`), and Planner's `_select_tool()`
resolves a Tool purely by `capability_id in tool.capabilities`
(`parika/core/planner/planner.py`) - so a single Tool instance has no
way to know which of several capabilities a given request targets.

The Filesystem Module therefore registers **one Tool per capability**,
each with its own `tool.filesystem_<operation>` identifier and its own
`FilesystemToolDriver` instance bound to that one operation. This
mirrors, at a larger scale, the exact "one Tool implements one
Capability" shape `create_runtime_info_tool()` and
`create_web_search_tool()` already established, and requires no
change to Planner, CapabilityResolver, CapabilityExecutor, or
ToolManager: each is registered and selected exactly like any other
single-capability Tool.

This module owns Tool creation. ToolManager only registers and stores
the Tool instances produced here; it does not create Tool objects
itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from parika.core.tool_manager.tool import Tool

FILESYSTEM_TOOL_VERSION = "1.0.0"

_PATH_PROPERTY: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path.",
}


class FilesystemOperation(StrEnum):
    """
    Every operation the Filesystem Tool implements, one per
    registered Capability.
    """

    READ = "read"
    WRITE = "write"
    LIST = "list"
    SEARCH = "search"
    COPY = "copy"
    MOVE = "move"
    DELETE = "delete"
    MKDIR = "mkdir"
    EXISTS = "exists"
    INFO = "info"
    WALK = "walk"
    PERMISSIONS = "permissions"
    WATCH = "watch"


@dataclass(frozen=True, slots=True, kw_only=True)
class FilesystemOperationSpec:
    """
    Everything needed to register one Filesystem Tool operation as
    its own Tool + Capability pair.
    """

    operation: FilesystemOperation
    capability_id: str
    tool_id: str
    name: str
    description: str
    purpose: str = ""
    use_when: str = ""
    avoid_when: str = ""
    requires: str = ""
    result_semantics: str = ""
    failure_semantics: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)
    """
    This operation's Tool Affordance Contract fields -- this Tool's
    own affordances. Registered as this Capability's
    `CapabilityDefinition.metadata["tool_affordance"]` (see
    `parika/modules/filesystem/driver.py`). AI Context Engineering
    only ever discovers these generically; it never defines or
    hardcodes them (see `parika/interfaces/ai_context/tool_context.py`).
    """


FILESYSTEM_OPERATIONS: tuple[FilesystemOperationSpec, ...] = (
    FilesystemOperationSpec(
        operation=FilesystemOperation.READ,
        capability_id="filesystem.read",
        tool_id="tool.filesystem_read",
        name="Filesystem Read",
        description="Reads the text content of a file.",
        purpose="Provides access to text content already stored in a local file.",
        use_when=(
            "the user wants to see, read, or use the contents of a "
            "specific local file."
        ),
        avoid_when=(
            "the content is already available from the conversation, "
            "injected Memory/Knowledge, or an earlier Tool result."
        ),
        requires="the file path; ask the user for it if not already known.",
        result_semantics=(
            "Returns the raw file contents. Present them directly "
            "unless the user asked for a summary or analysis."
        ),
        failure_semantics=(
            "If the path does not exist or cannot be read, explain the "
            "problem in plain language (e.g. 'that file could not be "
            "found') without exposing internal exception details."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": _PATH_PROPERTY,
                "encoding": {
                    "type": "string",
                    "description": "Text encoding. Defaults to 'utf-8'.",
                },
            },
            "required": ["path"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.WRITE,
        capability_id="filesystem.write",
        tool_id="tool.filesystem_write",
        name="Filesystem Write",
        description=(
            "Writes text content to a file, creating or overwriting "
            "it atomically."
        ),
        purpose="Provides the ability to create or update a local file's content.",
        use_when=(
            "the user explicitly asks to create, write, save, or "
            "update a file's content."
        ),
        avoid_when="the user has not asked for a file to be created or changed.",
        requires="the file path and the content to write.",
        result_semantics=(
            "Confirms the file was written. State plainly that it was "
            "saved; do not restate the raw tool response."
        ),
        failure_semantics=(
            "If writing fails (e.g. permission denied, invalid path), "
            "explain the problem naturally without exposing internal "
            "exception details."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": _PATH_PROPERTY,
                "content": {"type": "string", "description": "Text content to write."},
                "encoding": {"type": "string", "description": "Defaults to 'utf-8'."},
                "create_parents": {
                    "type": "boolean",
                    "description": "Create missing parent directories. Defaults to true.",
                },
                "append": {
                    "type": "boolean",
                    "description": "Append instead of overwriting. Defaults to false.",
                },
            },
            "required": ["path", "content"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.LIST,
        capability_id="filesystem.list",
        tool_id="tool.filesystem_list",
        name="Filesystem List",
        description="Lists the immediate entries of a directory.",
        purpose="Provides visibility into what a local directory currently contains.",
        use_when="the user wants to see what files or subdirectories a directory contains.",
        avoid_when="the listing is already available from an earlier Tool result in this conversation.",
        requires="the directory path; ask the user for it if not already known.",
        result_semantics=(
            "Returns a list of entry names. Present them naturally; "
            "summarize rather than dump raw output when there are many."
        ),
        failure_semantics=(
            "If the path does not exist or is not a directory, explain "
            "the problem in plain language."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": _PATH_PROPERTY,
                "pattern": {
                    "type": "string",
                    "description": "Optional glob pattern filter (e.g. '*.py').",
                },
            },
            "required": ["path"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.SEARCH,
        capability_id="filesystem.search",
        tool_id="tool.filesystem_search",
        name="Filesystem Search",
        description=(
            "Searches a directory tree for entries matching a "
            "glob-style filename pattern."
        ),
        purpose="Provides the ability to locate local files by name without knowing their exact path.",
        use_when="the user wants to find files matching a name or pattern within a directory tree.",
        avoid_when="the exact file path is already known - use Filesystem Read/Info directly instead.",
        requires="a starting directory path and a glob-style filename pattern (e.g. '*.py').",
        result_semantics=(
            "Returns matching paths. Summarize the matches in natural "
            "language; do not describe raw JSON."
        ),
        failure_semantics="If nothing matches, say so plainly rather than guessing a result.",
        parameters={
            "type": "object",
            "properties": {
                "path": _PATH_PROPERTY,
                "pattern": {
                    "type": "string",
                    "description": "Glob-style filename pattern (e.g. '*.py').",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Search subdirectories. Defaults to true.",
                },
            },
            "required": ["path", "pattern"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.COPY,
        capability_id="filesystem.copy",
        tool_id="tool.filesystem_copy",
        name="Filesystem Copy",
        description="Copies a file or directory to a new location.",
        purpose="Provides the ability to duplicate a local file or directory to a new location.",
        use_when="the user explicitly asks to copy or duplicate a file or directory.",
        avoid_when="the user has not asked for a copy to be made - never copy data speculatively.",
        requires="the source path and the destination path.",
        result_semantics="Confirms the copy succeeded. State plainly that it was done.",
        failure_semantics=(
            "If the copy fails (e.g. source missing, permission "
            "denied, destination exists), explain the problem "
            "naturally without exposing internal exception details."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": _PATH_PROPERTY,
                "destination": _PATH_PROPERTY,
                "overwrite": {
                    "type": "boolean",
                    "description": "Overwrite an existing destination. Defaults to false.",
                },
            },
            "required": ["source", "destination"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.MOVE,
        capability_id="filesystem.move",
        tool_id="tool.filesystem_move",
        name="Filesystem Move",
        description="Moves or renames a file or directory.",
        purpose="Provides the ability to relocate or rename a local file or directory.",
        use_when="the user explicitly asks to move or rename a file or directory.",
        avoid_when="the user has not asked for a move/rename - never relocate data speculatively.",
        requires="the source path and the destination path.",
        result_semantics="Confirms the move succeeded. State plainly that it was done.",
        failure_semantics=(
            "If the move fails (e.g. source missing, permission "
            "denied, destination exists), explain the problem "
            "naturally without exposing internal exception details."
        ),
        parameters={
            "type": "object",
            "properties": {
                "source": _PATH_PROPERTY,
                "destination": _PATH_PROPERTY,
                "overwrite": {
                    "type": "boolean",
                    "description": "Overwrite an existing destination. Defaults to false.",
                },
            },
            "required": ["source", "destination"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.DELETE,
        capability_id="filesystem.delete",
        tool_id="tool.filesystem_delete",
        name="Filesystem Delete",
        description="Deletes a file or directory.",
        purpose="Provides the ability to permanently remove a local file or directory.",
        use_when="the user explicitly and unambiguously asks to delete or remove a file or directory.",
        avoid_when=(
            "the request is ambiguous or was not clearly a deletion "
            "request - this is a destructive, irreversible operation; "
            "never call it speculatively or to 'clean up' unprompted."
        ),
        requires="the path to delete; a non-empty directory additionally requires explicit confirmation to delete recursively.",
        result_semantics="Confirms the deletion succeeded. State plainly that it was done.",
        failure_semantics=(
            "If deletion fails (e.g. permission denied, path missing), "
            "explain the problem naturally without exposing internal "
            "exception details."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": _PATH_PROPERTY,
                "recursive": {
                    "type": "boolean",
                    "description": "Required to delete a non-empty directory.",
                },
            },
            "required": ["path"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.MKDIR,
        capability_id="filesystem.mkdir",
        tool_id="tool.filesystem_mkdir",
        name="Filesystem Make Directory",
        description="Creates a directory, optionally with its parents.",
        purpose="Provides the ability to create a new local directory.",
        use_when="the user explicitly asks to create a directory/folder.",
        avoid_when="the user has not asked for a directory to be created.",
        requires="the directory path to create.",
        result_semantics="Confirms the directory was created. State plainly that it was done.",
        failure_semantics=(
            "If creation fails (e.g. permission denied, invalid path), "
            "explain the problem naturally without exposing internal "
            "exception details."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": _PATH_PROPERTY,
                "parents": {
                    "type": "boolean",
                    "description": "Create missing parents. Defaults to true.",
                },
                "exist_ok": {
                    "type": "boolean",
                    "description": "Do not error if it already exists. Defaults to true.",
                },
            },
            "required": ["path"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.EXISTS,
        capability_id="filesystem.exists",
        tool_id="tool.filesystem_exists",
        name="Filesystem Exists",
        description="Checks whether a path exists.",
        purpose="Provides a way to check whether a local path currently exists.",
        use_when="the user asks whether a specific file or directory exists.",
        avoid_when="existence is already known from an earlier Tool result in this conversation.",
        requires="the path to check.",
        result_semantics="Returns a plain true/false. State the answer directly and naturally.",
        failure_semantics="If the check itself fails unexpectedly, explain the problem naturally.",
        parameters={
            "type": "object",
            "properties": {"path": _PATH_PROPERTY},
            "required": ["path"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.INFO,
        capability_id="filesystem.info",
        tool_id="tool.filesystem_info",
        name="Filesystem Info",
        description=(
            "Returns metadata about a path: size, type, timestamps, "
            "and permissions."
        ),
        purpose="Provides metadata about a local path without reading its full content.",
        use_when="the user asks about a file/directory's size, type, timestamps, or permissions.",
        avoid_when="the user wants the file's actual content - use Filesystem Read instead.",
        requires="the path to inspect.",
        result_semantics="Summarize the relevant metadata naturally; do not dump the raw structure.",
        failure_semantics="If the path does not exist, explain the problem in plain language.",
        parameters={
            "type": "object",
            "properties": {"path": _PATH_PROPERTY},
            "required": ["path"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.WALK,
        capability_id="filesystem.walk",
        tool_id="tool.filesystem_walk",
        name="Filesystem Walk",
        description=(
            "Recursively lists every file and directory beneath a "
            "path."
        ),
        purpose="Provides a full inventory of a local directory tree.",
        use_when="the user wants an overview of everything under a directory, recursively.",
        avoid_when="a single directory's immediate contents suffice - use Filesystem List instead.",
        requires="the starting directory path.",
        result_semantics="Summarize the tree's contents naturally; do not dump every raw entry.",
        failure_semantics="If the path does not exist or is not a directory, explain the problem plainly.",
        parameters={
            "type": "object",
            "properties": {
                "path": _PATH_PROPERTY,
                "max_entries": {
                    "type": "integer",
                    "description": "Upper bound on returned entries.",
                },
            },
            "required": ["path"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.PERMISSIONS,
        capability_id="filesystem.permissions",
        tool_id="tool.filesystem_permissions",
        name="Filesystem Permissions",
        description=(
            "Returns the permission mode and read/write/execute "
            "access of a path."
        ),
        purpose="Provides visibility into a local path's permission mode.",
        use_when="the user asks whether a file/directory is readable, writable, or executable.",
        avoid_when="permission information is already available from an earlier Tool result.",
        requires="the path to inspect.",
        result_semantics="State the permissions naturally; do not dump the raw mode bits.",
        failure_semantics="If the path does not exist, explain the problem in plain language.",
        parameters={
            "type": "object",
            "properties": {"path": _PATH_PROPERTY},
            "required": ["path"],
        },
    ),
    FilesystemOperationSpec(
        operation=FilesystemOperation.WATCH,
        capability_id="filesystem.watch",
        tool_id="tool.filesystem_watch",
        name="Filesystem Watch",
        description=(
            "Observes a path for a bounded duration and reports "
            "created, modified, and deleted entries."
        ),
        purpose="Provides the ability to observe local filesystem changes over a bounded time window.",
        use_when="the user explicitly asks to monitor or watch a path for changes.",
        avoid_when="a one-time snapshot suffices - use Filesystem List/Walk instead.",
        requires="the path to observe; an optional duration and polling interval.",
        result_semantics="Summarize what changed naturally; do not dump the raw event log.",
        failure_semantics="If the path does not exist or observation fails, explain the problem plainly.",
        parameters={
            "type": "object",
            "properties": {
                "path": _PATH_PROPERTY,
                "interval_seconds": {
                    "type": "number",
                    "description": "Polling interval in seconds.",
                },
                "duration_seconds": {
                    "type": "number",
                    "description": (
                        "How long to observe for, in seconds (capped by "
                        "configuration)."
                    ),
                },
            },
            "required": ["path"],
        },
    ),
)
"""
Every Filesystem Tool operation PARIKA implements, in the order the
Filesystem Module registers them. Adding a future operation means
appending one entry here and one handler in `driver.py` - no other
module needs to change.
"""


def create_filesystem_tool(spec: FilesystemOperationSpec) -> Tool:
    """
    Build the immutable Tool descriptor for one Filesystem Tool
    operation.

    Args:
        spec:
            The operation's registration spec (see
            `FILESYSTEM_OPERATIONS`).

    Returns:
        A Tool ready to be registered with ToolManager alongside a
        `FilesystemToolDriver` bound to `spec.operation`.
    """

    return Tool(
        id=spec.tool_id,
        name=spec.name,
        version=FILESYSTEM_TOOL_VERSION,
        description=spec.description,
        capabilities=(spec.capability_id,),
    )
