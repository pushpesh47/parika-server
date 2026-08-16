"""
PARIKA Weather Tool package.

Implements the `weather.current` and `weather.forecast` Capabilities
using Open-Meteo (https://open-meteo.com), a free, keyless weather
API - no API key or account required.

Public exports provide everything needed to register these Tools with
ToolManager, either directly or through the Weather Module.
"""

from __future__ import annotations

from .config import WeatherToolConfig, load_weather_config
from .driver import WeatherToolDriver
from .exceptions import (
    InvalidWeatherArgumentError,
    LocationNotFoundError,
    WeatherNetworkError,
    WeatherTimeoutError,
    WeatherToolError,
)
from .geocoding import GeocodeResult, geocode
from .manifest import (
    WEATHER_CAPABILITY_CURRENT,
    WEATHER_CAPABILITY_FORECAST,
    WEATHER_TOOL_ID_CURRENT,
    WEATHER_TOOL_ID_FORECAST,
    WEATHER_TOOL_VERSION,
    WeatherMode,
    create_weather_current_tool,
    create_weather_forecast_tool,
)
from .transport import HttpResponse, HttpTransport, UrllibHttpTransport

__all__ = [
    "WEATHER_CAPABILITY_CURRENT",
    "WEATHER_CAPABILITY_FORECAST",
    "WEATHER_TOOL_ID_CURRENT",
    "WEATHER_TOOL_ID_FORECAST",
    "WEATHER_TOOL_VERSION",
    "GeocodeResult",
    "HttpResponse",
    "HttpTransport",
    "InvalidWeatherArgumentError",
    "LocationNotFoundError",
    "UrllibHttpTransport",
    "WeatherMode",
    "WeatherNetworkError",
    "WeatherTimeoutError",
    "WeatherToolConfig",
    "WeatherToolDriver",
    "WeatherToolError",
    "create_weather_current_tool",
    "create_weather_forecast_tool",
    "geocode",
    "load_weather_config",
]
