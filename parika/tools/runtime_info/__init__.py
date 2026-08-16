"""
PARIKA Runtime Info Tool.

Deterministic current date/time information, read from the system
clock via the standard library only - no network access, no AI
provider call. Exists so PARIKA never has to rely on an LLM's own
(frequently stale or hallucinated) notion of "now".
"""

from .driver import RuntimeInfoToolDriver
from .exceptions import RuntimeInfoToolError, UnknownTimezoneError
from .manifest import (
    RUNTIME_INFO_CAPABILITY_ID,
    RUNTIME_INFO_TOOL_ID,
    create_runtime_info_tool,
)
from .timezones import resolve_timezone

__all__ = [
    "RUNTIME_INFO_CAPABILITY_ID",
    "RUNTIME_INFO_TOOL_ID",
    "RuntimeInfoToolDriver",
    "RuntimeInfoToolError",
    "UnknownTimezoneError",
    "create_runtime_info_tool",
    "resolve_timezone",
]
