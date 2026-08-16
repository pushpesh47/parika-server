"""
PARIKA Weather Module - Manifest

Defines the static ModuleManifest describing the Weather Module.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .driver import WeatherModuleDriver

WEATHER_MODULE_ID = "weather"
WEATHER_MODULE_VERSION = "1.0.0"


def create_weather_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Weather Module.
    """

    return ModuleManifest(
        id=WEATHER_MODULE_ID,
        name="Weather",
        version=WEATHER_MODULE_VERSION,
        description=(
            "Provides the weather.current and weather.forecast "
            "Capabilities using Open-Meteo, a free, keyless weather "
            "API."
        ),
        author="PARIKA",
        license="MIT",
        tags=("weather", "network"),
        required_permissions=("network.fetch",),
        driver=(
            "parika.modules.weather.driver.WeatherModuleDriver"
        ),
    )


def create_weather_module(driver: WeatherModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Weather Module.

    Args:
        driver:
            Constructed WeatherModuleDriver instance for this module.

    Returns:
        A Module ready to be registered with ModuleManager.
    """

    return Module(
        id=WEATHER_MODULE_ID,
        manifest=create_weather_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
