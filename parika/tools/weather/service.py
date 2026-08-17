"""
PARIKA Weather API - Service

Provides structured weather data from Open-Meteo with caching.
Independent of CoreExecutionOwner - runs directly in the API layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from parika.core.configuration.configuration import Configuration
from parika.core.logger.logger import Logger
from parika.tools.weather.cache import WeatherCache, make_cache_key
from parika.tools.weather.config import load_weather_config
from parika.tools.weather.exceptions import WeatherNetworkError, WeatherTimeoutError
from parika.tools.weather.geocoding import reverse_geocode
from parika.tools.weather.transport import HttpTransport, UrllibHttpTransport
from parika.tools.weather.weather_codes import describe_weather_code

FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"

_CURRENT_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "showers",
    "snowfall",
    "weather_code",
    "cloud_cover",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "visibility",
    "is_day",
)

_DAILY_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "sunrise",
    "sunset",
    "wind_speed_10m_max",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class WeatherServiceConfig:
    """Resolved configuration for WeatherService."""

    timeout_seconds: float
    max_attempts: int
    backoff_seconds: float
    cache_ttl_seconds: float
    units: str
    default_forecast_days: int


class WeatherService:
    """
    Direct weather API service with caching.

    Does NOT go through CoreExecutionOwner, Brain, Planner, or any
    reasoning pipeline. Remains responsive while Core is busy.
    """

    def __init__(
        self,
        configuration: Configuration | None,
        logger: Logger,
        transport: HttpTransport | None = None,
        cache: WeatherCache | None = None,
    ) -> None:
        self._logger = logger.get_logger(__name__)
        self._transport = transport or UrllibHttpTransport()

        weather_config = load_weather_config(configuration)
        self._config = WeatherServiceConfig(
            timeout_seconds=weather_config.timeout_seconds,
            max_attempts=weather_config.max_attempts,
            backoff_seconds=weather_config.backoff_seconds,
            cache_ttl_seconds=weather_config.cache_ttl_seconds,
            units=weather_config.units,
            default_forecast_days=weather_config.default_forecast_days,
        )

        self._cache = cache

    def _units_for(self) -> dict[str, str]:
        # Direct Weather API always uses metric units for stable contract.
        # Field names like temperature_c, wind_speed_kmh, precipitation_mm
        # imply metric units. The configured units setting applies to the
        # Chat weather Tool path, not this direct API.
        return {
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        }

    def _build_params(self, latitude: float, longitude: float) -> dict[str, Any]:
        return {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "auto",
            "forecast_days": self._config.default_forecast_days,
            "current": ",".join(_CURRENT_FIELDS),
            "daily": ",".join(_DAILY_FIELDS),
            **self._units_for(),
        }

    async def _fetch_from_provider(
        self, latitude: float, longitude: float
    ) -> dict[str, Any]:
        """Fetch raw weather data from Open-Meteo."""
        params = self._build_params(latitude, longitude)
        url = f"{FORECAST_ENDPOINT}?{urlencode(params)}"

        for attempt in range(1, self._config.max_attempts + 1):
            try:
                response = self._transport.get(
                    url, timeout=self._config.timeout_seconds
                )

                if response.status_code >= 400:
                    body_preview = (
                        response.body[:500].decode("utf-8", errors="replace")
                        if response.body
                        else ""
                    )
                    self._logger.error(
                        "Weather provider request failed: provider=Open-Meteo "
                        f"status={response.status_code} latitude={latitude} "
                        f"longitude={longitude} response={body_preview}"
                    )
                    raise WeatherNetworkError(
                        f"Open-Meteo returned HTTP {response.status_code}."
                    )

                try:
                    payload = json.loads(
                        response.body.decode("utf-8", errors="replace")
                    )
                except json.JSONDecodeError as ex:
                    self._logger.error(
                        "Weather provider response malformed: provider=Open-Meteo "
                        f"latitude={latitude} longitude={longitude} error={ex}"
                    )
                    raise WeatherNetworkError(
                        "Open-Meteo response could not be parsed as JSON."
                    ) from ex

                if "current" not in payload:
                    self._logger.error(
                        "Weather provider response missing required fields: "
                        f"provider=Open-Meteo latitude={latitude} longitude={longitude}"
                    )
                    raise WeatherNetworkError(
                        "Open-Meteo response missing required 'current' field."
                    )

                self._logger.debug(
                    "Weather provider refresh completed: provider=Open-Meteo "
                    f"latitude={latitude} longitude={longitude}"
                )
                return payload

            except WeatherTimeoutError as ex:
                self._logger.error(
                    "Weather provider request timeout: provider=Open-Meteo "
                    f"latitude={latitude} longitude={longitude} "
                    f"exception={type(ex).__name__} message={ex}"
                )
                if attempt == self._config.max_attempts:
                    raise
                await asyncio.sleep(self._config.backoff_seconds * attempt)

            except WeatherNetworkError as ex:
                # Log transport-level network errors (connection refused, DNS failure, etc.)
                # HTTP errors, malformed JSON, and missing fields are already logged above
                if attempt == 1:  # Only log on first attempt to avoid spam
                    self._logger.error(
                        "Weather provider request failed: provider=Open-Meteo "
                        f"latitude={latitude} longitude={longitude} "
                        f"exception={type(ex).__name__} message={ex}"
                    )
                if attempt == self._config.max_attempts:
                    raise
                await asyncio.sleep(self._config.backoff_seconds * attempt)

        raise WeatherNetworkError("Failed to fetch weather data after retries")

    def _normalize_current(
        self, payload: dict[str, Any], latitude: float, longitude: float
    ) -> dict[str, Any]:
        current = payload.get("current", {})
        weather_code = current.get("weather_code")
        is_day = bool(current.get("is_day", 1))

        return {
            "temperature_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "condition": describe_weather_code(weather_code),
            "weather_code": weather_code,
            "icon": self._weather_code_to_icon(weather_code, is_day),
            "is_day": is_day,
            "humidity_percent": current.get("relative_humidity_2m"),
            "precipitation_mm": current.get("precipitation"),
            "rain_mm": current.get("rain"),
            "showers_mm": current.get("showers"),
            "snowfall_mm": current.get("snowfall"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "wind_direction_degrees": current.get("wind_direction_10m"),
            "wind_gusts_kmh": current.get("wind_gusts_10m"),
            "cloud_cover_percent": current.get("cloud_cover"),
            "pressure_hpa": current.get("surface_pressure"),
            "visibility_m": current.get("visibility"),
            "observed_at": current.get("time"),
        }

    def _normalize_forecast(
        self, payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        daily = payload.get("daily", {})
        times = daily.get("time", [])

        forecast = []
        for index, day in enumerate(times):
            weather_code = daily.get("weather_code", [])[index] if index < len(daily.get("weather_code", [])) else None
            is_day = True  # Daily forecast doesn't have is_day, assume day

            forecast.append({
                "date": day,
                "condition": describe_weather_code(weather_code),
                "weather_code": weather_code,
                "icon": self._weather_code_to_icon(weather_code, True),
                "temperature_max_c": daily.get("temperature_2m_max", [])[index] if index < len(daily.get("temperature_2m_max", [])) else None,
                "temperature_min_c": daily.get("temperature_2m_min", [])[index] if index < len(daily.get("temperature_2m_min", [])) else None,
                "feels_like_max_c": daily.get("apparent_temperature_max", [])[index] if index < len(daily.get("apparent_temperature_max", [])) else None,
                "feels_like_min_c": daily.get("apparent_temperature_min", [])[index] if index < len(daily.get("apparent_temperature_min", [])) else None,
                "precipitation_probability_percent": daily.get("precipitation_probability_max", [])[index] if index < len(daily.get("precipitation_probability_max", [])) else None,
                "precipitation_sum_mm": daily.get("precipitation_sum", [])[index] if index < len(daily.get("precipitation_sum", [])) else None,
                "sunrise": daily.get("sunrise", [])[index] if index < len(daily.get("sunrise", [])) else None,
                "sunset": daily.get("sunset", [])[index] if index < len(daily.get("sunset", [])) else None,
            })

        return forecast

    def _weather_code_to_icon(self, code: int | None, is_day: bool) -> str | None:
        """Map WMO weather code + day/night to semantic icon identifier."""
        if code is None:
            return None

        # Clear sky
        if code == 0:
            return "clear-day" if is_day else "clear-night"
        # Mainly clear
        if code == 1:
            return "partly-cloudy-day" if is_day else "partly-cloudy-night"
        # Partly cloudy
        if code == 2:
            return "partly-cloudy-day" if is_day else "partly-cloudy-night"
        # Overcast
        if code == 3:
            return "cloudy"
        # Fog
        if code in (45, 48):
            return "fog"
        # Drizzle
        if code in (51, 53, 55, 56, 57):
            return "rain"
        # Rain
        if code in (61, 63, 65, 66, 67, 80, 81, 82):
            return "rain"
        # Snow
        if code in (71, 73, 75, 77, 85, 86):
            return "snow"
        # Thunderstorm
        if code in (95, 96, 99):
            return "thunderstorm"

        return "cloudy"

    def _resolve_location_name(
        self, payload: dict[str, Any], latitude: float, longitude: float
    ) -> str:
        """Extract location name from provider response or construct from coordinates."""
        # Try reverse geocoding for a human-readable name
        # This is best-effort; if it fails or times out, fall back to coordinates
        try:
            name = reverse_geocode(
                latitude,
                longitude,
                transport=self._transport,
                timeout_seconds=2.0,  # Short timeout for reverse geocoding
            )
            if name:
                return name
        except Exception:
            pass

        # Fallback to coordinate-based name
        return f"{latitude:.4f}, {longitude:.4f}"

    async def get_weather(
        self, latitude: float, longitude: float
    ) -> dict[str, Any]:
        """
        Get weather data for coordinates with caching.

        Returns normalized response with current conditions, forecast,
        and metadata including cache status.
        """
        # Normalize coordinates for cache key
        cache_key = make_cache_key(latitude, longitude)

        async def fetch_and_normalize() -> dict[str, Any]:
            payload = await self._fetch_from_provider(latitude, longitude)

            current = self._normalize_current(payload, latitude, longitude)
            forecast = self._normalize_forecast(payload)
            location_name = self._resolve_location_name(payload, latitude, longitude)
            tz_name = payload.get("timezone", "UTC")

            now = datetime.now(timezone.utc).isoformat()
            cached_at = now
            expires_at = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + self._config.cache_ttl_seconds,
                tz=timezone.utc
            ).isoformat()

            return {
                "location": {
                    "name": location_name,
                    "latitude": latitude,
                    "longitude": longitude,
                    "timezone": tz_name,
                },
                "current": current,
                "forecast": forecast,
                "metadata": {
                    "fetched_at": now,
                    "cached_at": cached_at,
                    "cache_expires_at": expires_at,
                    "cache_status": "fresh",
                    "cache_ttl_seconds": self._config.cache_ttl_seconds,
                },
            }

        if self._cache is not None:
            data, cache_status = await self._cache.get_or_fetch(
                cache_key, fetch_and_normalize
            )
            # Update cache status in metadata
            data["metadata"]["cache_status"] = cache_status
            if cache_status == "fetched":
                self._logger.debug(
                    "Weather data fetched from provider: key=%s", cache_key
                )
            return data

        # No cache - fetch directly
        return await fetch_and_normalize()


import asyncio