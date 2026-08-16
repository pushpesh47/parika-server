"""
PARIKA Weather Module package.

Integrates the Weather Tool into PARIKA through ModuleManager,
CapabilityRegistry, and ToolManager.
"""

from __future__ import annotations

from .driver import MODULE_HEALTH_COMPONENT_ID, WeatherModuleDriver
from .manifest import (
    WEATHER_MODULE_ID,
    WEATHER_MODULE_VERSION,
    create_weather_module,
    create_weather_module_manifest,
)

__all__ = [
    "MODULE_HEALTH_COMPONENT_ID",
    "WEATHER_MODULE_ID",
    "WEATHER_MODULE_VERSION",
    "WeatherModuleDriver",
    "create_weather_module",
    "create_weather_module_manifest",
]
