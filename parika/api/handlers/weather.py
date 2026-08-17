"""
PARIKA API - Weather Handler

Provides the internal Core Router binding for the Weather operation.

The handler uses the API-owned WeatherService (shared WeatherCache) and
does NOT go through CoreExecutionOwner. This preserves Core independence:
the external HTTP Weather API remains responsive while Core is busy.
"""

from __future__ import annotations

from parika.tools.weather.service import WeatherService

from ..requests import WeatherRequest


def handle_weather(service: WeatherService, request: WeatherRequest) -> dict[str, Any]:
    """
    Get weather data for coordinates using the shared WeatherCache.

    This is the internal handler for the Core Router binding. The
    external FastAPI endpoint also calls this same handler via the
    API-owned WeatherService dependency.
    """
    import asyncio

    result = asyncio.run(service.get_weather(request.latitude, request.longitude))
    return result