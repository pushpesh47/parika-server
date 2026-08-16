"""
PARIKA Weather Tool Exceptions

Defines the exception hierarchy used by the Weather Tool.

All Weather Tool exceptions derive from `WeatherToolError` so that
`ToolManager` can uniformly wrap them as `ToolExecutionError`, exactly
like every other Tool in PARIKA (see `runtime_info` and
`web_search`).
"""

from __future__ import annotations


class WeatherToolError(Exception):
    """
    Base exception for all Weather Tool errors.
    """


class InvalidWeatherArgumentError(WeatherToolError):
    """
    Raised when a request is missing a required argument, or supplies
    an invalid one (e.g. an empty `location`).
    """


class LocationNotFoundError(WeatherToolError):
    """
    Raised when the geocoding step cannot resolve a location name to
    coordinates.
    """


class WeatherTimeoutError(WeatherToolError):
    """
    Raised when a network operation exceeds the configured timeout.
    """


class WeatherNetworkError(WeatherToolError):
    """
    Raised when a network operation fails for a reason other than a
    timeout, or the provider returns a malformed response.
    """
