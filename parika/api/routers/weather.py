"""
PARIKA API - Weather Router

Direct weather API endpoint for structured weather data.
Independent of CoreExecutionOwner - remains responsive while Core is busy.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..auth.dependency import RequireAuth
from ..auth.backend import AuthContext
from ..dependencies import get_weather_service
from ..handlers.weather import handle_weather
from ..requests import WeatherRequest
from ..schemas.weather import WeatherResponse
from parika.tools.weather.service import WeatherService

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("", response_model=WeatherResponse)
def get_weather(
    latitude: float = Query(..., ge=-90, le=90, description="Latitude in decimal degrees"),
    longitude: float = Query(..., ge=-180, le=180, description="Longitude in decimal degrees"),
    auth: AuthContext = RequireAuth,
    service: WeatherService = Depends(get_weather_service),
) -> WeatherResponse:
    """
    Get current weather and short forecast for coordinates.

    Returns structured weather data suitable for a dashboard/card UI.
    Cached for 20 minutes (configurable) to support 5-second Web Client polling
    without hitting the external provider on every request.

    This endpoint does NOT go through CoreExecutionOwner and remains
    responsive while Core is performing long-running operations.

    Query Parameters:
        latitude: Latitude in decimal degrees (-90 to 90)
        longitude: Longitude in decimal degrees (-180 to 180)

    Response:
        location: Resolved location info (name, coordinates, timezone)
        current: Current weather conditions (temperature, condition, wind, etc.)
        forecast: Daily forecast for next 5 days
        metadata: Cache info (fetched_at, cache_status, cache_expires_at)

    Cache Behavior:
        - Cache TTL: 20 minutes (1200 seconds) by default, configurable via [weather].cache_ttl_seconds
        - Cache key: Normalized coordinates (4 decimal places ~11m precision)
        - Stampede prevention: Concurrent requests after expiry trigger only one provider fetch
        - Web Client may poll every 5 seconds; provider called at most once per TTL window

    Errors:
        400: Invalid latitude/longitude
        401: Authentication required (per [api.auth].mode)
        500: Provider unavailable or malformed response
    """
    request = WeatherRequest(latitude=latitude, longitude=longitude)
    result = handle_weather(service, request)
    return WeatherResponse.model_validate(result)