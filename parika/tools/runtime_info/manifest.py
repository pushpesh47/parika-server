"""
PARIKA Runtime Info Tool - Manifest

Defines the static Tool metadata describing the Runtime Info Tool,
including its `RUNTIME_INFO_TOOL_AFFORDANCE` -- the Tool Affordance
Contract (name/description/use-and-avoid guidance/requirements/
result-and-failure semantics/JSON Schema parameters) AI Context
Engineering advertises for this capability. The Runtime Info Tool owns
this contract entirely; AI Context Engineering only ever discovers and
assembles it (see `parika/interfaces/ai_context/tool_context.py`) --
it never defines or hardcodes it.

This module owns Tool creation. ToolManager only registers and stores
the Tool instance produced here; it does not create Tool objects
itself.
"""

from __future__ import annotations

from typing import Any, Mapping

from parika.core.tool_manager.tool import Tool

RUNTIME_INFO_CAPABILITY_ID = "runtime.current_datetime"
"""
Identifier of the Capability implemented by this Tool.
"""

RUNTIME_INFO_TOOL_ID = "tool.runtime_info"
"""
Identifier of the Tool registered with ToolManager.
"""

RUNTIME_INFO_TOOL_VERSION = "1.0.0"

RUNTIME_INFO_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "name": "get_current_datetime",
    "description": (
        "Get the current date and time, optionally in a specific "
        "timezone. Always use this instead of guessing when asked "
        "for the current date, time, or day of the week."
    ),
    "purpose": (
        "Provides the real current date/time, since your own sense "
        "of 'now' is not reliable and is frozen at training time."
    ),
    "use_when": (
        "the user asks for the current date, time, or day of the "
        "week, or you need 'now' to resolve a relative timeframe "
        "(e.g. 'this week', 'today')."
    ),
    "avoid_when": (
        "the user is asking about a specific past or future date/"
        "time that does not require knowing the current moment, or "
        "the current date/time is already available from earlier in "
        "this conversation."
    ),
    "requires": (
        "nothing required; an optional timezone (IANA name or common "
        "abbreviation)."
    ),
    "result_semantics": (
        "Returns the exact current date/time. State it directly and "
        "naturally as part of your answer; do not describe it as tool "
        "output."
    ),
    "failure_semantics": (
        "If a supplied timezone is not recognized, ask the user to "
        "clarify or provide a standard name/abbreviation rather than "
        "guessing one."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": (
                    "IANA timezone name (e.g. 'Asia/Kolkata') or a "
                    "common abbreviation (e.g. 'IST', 'UTC', 'EST'). "
                    "Defaults to UTC when omitted."
                ),
            },
        },
        "required": [],
    },
}
"""
The Tool Affordance Contract for `runtime.current_datetime`,
registered as this Capability's `CapabilityDefinition.
metadata["tool_affordance"]` (see
`parika/modules/runtime_info/driver.py`). Includes an explicit `name`
override (`get_current_datetime`) since the generic
`id.replace(".", "_")` naming rule AI Context Engineering otherwise
applies would produce `runtime_current_datetime` instead.
"""


def create_runtime_info_tool() -> Tool:
    """
    Build the immutable Tool descriptor for the Runtime Info Tool.

    Returns:
        A Tool ready to be registered with ToolManager alongside a
        RuntimeInfoToolDriver instance.
    """

    return Tool(
        id=RUNTIME_INFO_TOOL_ID,
        name="Runtime Info",
        version=RUNTIME_INFO_TOOL_VERSION,
        description=(
            "Returns the current date and time, optionally in a "
            "specific timezone, read from the system clock."
        ),
        capabilities=(RUNTIME_INFO_CAPABILITY_ID,),
    )
