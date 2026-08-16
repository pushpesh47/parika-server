"""
PARIKA Weather Tool - Manifest

Defines the static Tool metadata describing the Weather Tool's two
Capabilities, including `WEATHER_TOOL_AFFORDANCES` -- the Tool
Affordance Contract (purpose, use/avoid guidance, requirements,
result/failure semantics, and JSON Schema parameters) for each, keyed
by capability id. The Weather Tool owns these contracts entirely; AI
Context Engineering only ever discovers and assembles them (see
`parika/interfaces/ai_context/tool_context.py`) -- it never defines
or hardcodes them.

Like the Filesystem Tool, `weather.current` and `weather.forecast`
are each registered as their own Tool (`WeatherToolDriver` bound to
one `WeatherMode` per instance), since `ToolRequest` carries no
capability identifier for a single Tool to dispatch on. See
`parika/tools/filesystem/manifest.py`'s module docstring for the full
reasoning; the same constraint applies here.

This module owns Tool creation. ToolManager only registers and stores
the Tool instances produced here; it does not create Tool objects
itself.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from parika.core.tool_manager.tool import Tool

WEATHER_TOOL_VERSION = "1.0.0"


class WeatherMode(StrEnum):
    """
    The two Capabilities the Weather Tool implements.
    """

    CURRENT = "current"
    FORECAST = "forecast"


WEATHER_CAPABILITY_CURRENT = "weather.current"
WEATHER_CAPABILITY_FORECAST = "weather.forecast"

WEATHER_TOOL_ID_CURRENT = "tool.weather_current"
WEATHER_TOOL_ID_FORECAST = "tool.weather_forecast"

_WEATHER_LOCATION_USE_WHEN = (
    "the user asks about current or upcoming weather conditions for "
    "a location."
)
_WEATHER_LOCATION_AVOID_WHEN = (
    "weather information is already available from the conversation, "
    "injected Memory/Knowledge, or an earlier Tool result in this "
    "conversation."
)
_WEATHER_LOCATION_REQUIRES = (
    "a location; ask the user for one if it was not given."
)
_WEATHER_FAILURE_SEMANTICS = (
    "If the location cannot be resolved, ask the user for "
    "clarification rather than guessing a place."
)

WEATHER_TOOL_AFFORDANCES: Mapping[str, Mapping[str, Any]] = {
    WEATHER_CAPABILITY_CURRENT: {
        "description": "Get current weather conditions for a location.",
        "purpose": (
            "Provides real-time weather conditions, since your own "
            "knowledge is not current."
        ),
        "use_when": _WEATHER_LOCATION_USE_WHEN,
        "avoid_when": _WEATHER_LOCATION_AVOID_WHEN,
        "requires": _WEATHER_LOCATION_REQUIRES,
        "result_semantics": (
            "Returns structured current-conditions data. Summarize "
            "the conditions naturally; do not describe the raw "
            "fields."
        ),
        "failure_semantics": _WEATHER_FAILURE_SEMANTICS,
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Free-text place name, e.g. 'Bengaluru'.",
                },
            },
            "required": ["location"],
        },
    },
    WEATHER_CAPABILITY_FORECAST: {
        "description": "Get a multi-day daily weather forecast for a location.",
        "purpose": (
            "Provides an upcoming weather forecast, since your own "
            "knowledge is not current."
        ),
        "use_when": _WEATHER_LOCATION_USE_WHEN,
        "avoid_when": _WEATHER_LOCATION_AVOID_WHEN,
        "requires": (
            f"{_WEATHER_LOCATION_REQUIRES} An optional number of "
            "forecast days."
        ),
        "result_semantics": (
            "Returns structured daily forecast data. Summarize the "
            "forecast naturally; do not describe the raw fields."
        ),
        "failure_semantics": _WEATHER_FAILURE_SEMANTICS,
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Free-text place name, e.g. 'Bengaluru'.",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of forecast days (1-16). Defaults to 5.",
                },
            },
            "required": ["location"],
        },
    },
}
"""
Tool Affordance Contracts for `weather.current`/`weather.forecast`,
registered as each Capability's `CapabilityDefinition.
metadata["tool_affordance"]` (see `parika/modules/weather/driver.py`).
"""


def create_weather_current_tool() -> Tool:
    """
    Build the immutable Tool descriptor for `weather.current`.
    """

    return Tool(
        id=WEATHER_TOOL_ID_CURRENT,
        name="Weather Current",
        version=WEATHER_TOOL_VERSION,
        description=(
            "Returns current weather conditions for a location, "
            "using Open-Meteo."
        ),
        capabilities=(WEATHER_CAPABILITY_CURRENT,),
    )


def create_weather_forecast_tool() -> Tool:
    """
    Build the immutable Tool descriptor for `weather.forecast`.
    """

    return Tool(
        id=WEATHER_TOOL_ID_FORECAST,
        name="Weather Forecast",
        version=WEATHER_TOOL_VERSION,
        description=(
            "Returns a multi-day daily weather forecast for a "
            "location, using Open-Meteo."
        ),
        capabilities=(WEATHER_CAPABILITY_FORECAST,),
    )
