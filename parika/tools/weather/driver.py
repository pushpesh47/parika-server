"""
PARIKA Weather Tool - Driver

Implements the `ToolDriver` contract for the `weather.current` and
`weather.forecast` Capabilities using Open-Meteo
(https://open-meteo.com) - a free, keyless weather API.

A single `WeatherToolDriver` instance is bound to exactly one
`WeatherMode` at construction time (see `manifest.py`'s module
docstring). The Weather Module constructs two instances - one per
Capability - and registers each as its own Tool.

Every request is resolved in two network steps: geocoding the
caller's free-text `location` into coordinates (`geocoding.py`), then
requesting current conditions or a daily forecast for those
coordinates from Open-Meteo's forecast API. No API key is required
for either step.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse

from .config import DEFAULT_FORECAST_DAYS
from .exceptions import (
    InvalidWeatherArgumentError,
    WeatherNetworkError,
    WeatherTimeoutError,
)
from .geocoding import geocode
from .manifest import WeatherMode
from .retry import retry_with_backoff
from .transport import HttpTransport
from .weather_codes import describe_weather_code
from parika.core.forensic_log import get_current_trace_id

FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"

_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    WeatherTimeoutError,
    WeatherNetworkError,
)

_CURRENT_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "weather_code",
    "wind_speed_10m",
    "wind_direction_10m",
    "is_day",
)

_DAILY_FIELDS = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
)


def _units_for(units: str) -> dict[str, str]:
    if units == "imperial":
        return {
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
        }

    return {
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }


class WeatherToolDriver:
    """
    ToolDriver implementing one Weather Tool Capability.
    """

    def __init__(
        self,
        mode: WeatherMode,
        *,
        transport: HttpTransport,
        units: str = "metric",
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        default_forecast_days: int = DEFAULT_FORECAST_DAYS,
    ) -> None:
        """
        Initialize the driver for one Capability.

        Args:
            mode:
                Whether this instance implements `weather.current` or
                `weather.forecast`.

            transport:
                HttpTransport used for both the geocoding request and
                the forecast request.

            units:
                `"metric"` or `"imperial"`.

            timeout_seconds:
                Maximum time, in seconds, to wait for each request.

            max_attempts:
                Maximum attempts per request, including the first.

            backoff_seconds:
                Base linear backoff delay between retry attempts.

            default_forecast_days:
                Default number of daily forecast entries returned by
                `weather.forecast` when the caller does not specify
                `days`.
        """

        self._mode = mode
        self._transport = transport
        self._units = units
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._default_forecast_days = default_forecast_days

    def execute(self, request: ToolRequest) -> ToolResponse:
        """
        Execute this driver's bound Capability.

        Expected `request.arguments`:
            location (str):
                Required free-text place name (e.g. "Bengaluru").

            days (int):
                Optional number of forecast days, `weather.forecast`
                only. Defaults to `default_forecast_days`, clamped to
                Open-Meteo's supported range (1-16).

        Raises:
            InvalidWeatherArgumentError:
                If `location` is missing, empty, or not a string.

            LocationNotFoundError:
                If `location` cannot be geocoded.

            WeatherTimeoutError:
                If a network request times out on every attempt.

            WeatherNetworkError:
                If a network request fails for another reason on
                every attempt, or a response is malformed.
        """

        location = request.arguments.get("location")

        if not isinstance(location, str) or not location.strip():
            raise InvalidWeatherArgumentError(
                "request.arguments['location'] must be a non-empty "
                "string."
            )

        place = retry_with_backoff(
            lambda: geocode(
                location,
                transport=self._transport,
                timeout_seconds=self._timeout_seconds,
            ),
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
            retryable_exceptions=_RETRYABLE_EXCEPTIONS,
        )

        if self._mode is WeatherMode.CURRENT:
            payload = self._fetch(place.latitude, place.longitude, forecast_days=1)
            result = self._build_current_result(place, payload)
        else:
            raw_days: Any = request.arguments.get(
                "days", self._default_forecast_days
            )
            days = max(1, min(int(raw_days), 16))
            payload = self._fetch(
                place.latitude, place.longitude, forecast_days=days
            )
            result = self._build_forecast_result(place, payload, days=days)

        # FORENSIC: Log raw tool output
        trace_id = get_current_trace_id()
        if trace_id:
            from parika.core.forensic_log import log_tool_result
            log_tool_result(
                trace_id=trace_id,
                goal_id="",
                task_id="",
                capability_id=self._mode.value,
                tool_id=f"tool.weather_{self._mode.value}",
                success=True,
                result=result,
                result_type="dict",
            )

        return ToolResponse(
            result=result,
            attributes={"location": location, "units": self._units},
        )

    def _fetch(
        self,
        latitude: float,
        longitude: float,
        *,
        forecast_days: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "auto",
            "forecast_days": forecast_days,
            **_units_for(self._units),
        }

        if self._mode is WeatherMode.CURRENT:
            params["current"] = ",".join(_CURRENT_FIELDS)
        else:
            params["daily"] = ",".join(_DAILY_FIELDS)

        url = f"{FORECAST_ENDPOINT}?{urlencode(params)}"

        def _request() -> dict[str, Any]:
            response = self._transport.get(url, timeout=self._timeout_seconds)

            if response.status_code >= 400:
                raise WeatherNetworkError(
                    f"Open-Meteo returned HTTP {response.status_code}."
                )

            try:
                return json.loads(
                    response.body.decode("utf-8", errors="replace")
                )
            except json.JSONDecodeError as ex:
                raise WeatherNetworkError(
                    "Open-Meteo returned a malformed JSON response."
                ) from ex

        return retry_with_backoff(
            _request,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
            retryable_exceptions=_RETRYABLE_EXCEPTIONS,
        )

    def _build_current_result(
        self,
        place: Any,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        current = payload.get("current", {})
        weather_code = current.get("weather_code")

        return {
            "location": place.name,
            "country": place.country,
            "latitude": place.latitude,
            "longitude": place.longitude,
            "timezone": payload.get("timezone", place.timezone),
            "time": current.get("time"),
            "temperature": current.get("temperature_2m"),
            "apparent_temperature": current.get("apparent_temperature"),
            "relative_humidity": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "wind_speed": current.get("wind_speed_10m"),
            "wind_direction": current.get("wind_direction_10m"),
            "is_day": bool(current.get("is_day")),
            "weather_code": weather_code,
            "description": describe_weather_code(weather_code),
            "units": _units_for(self._units),
        }

    def _build_forecast_result(
        self,
        place: Any,
        payload: dict[str, Any],
        *,
        days: int,
    ) -> dict[str, Any]:
        daily = payload.get("daily", {})
        times = daily.get("time", [])

        entries: list[dict[str, Any]] = []

        for index, day in enumerate(times):
            weather_code = _at(daily.get("weather_code"), index)

            entries.append(
                {
                    "date": day,
                    "temperature_max": _at(daily.get("temperature_2m_max"), index),
                    "temperature_min": _at(daily.get("temperature_2m_min"), index),
                    "precipitation_sum": _at(
                        daily.get("precipitation_sum"), index
                    ),
                    "wind_speed_max": _at(
                        daily.get("wind_speed_10m_max"), index
                    ),
                    "weather_code": weather_code,
                    "description": describe_weather_code(weather_code),
                }
            )

        return {
            "location": place.name,
            "country": place.country,
            "latitude": place.latitude,
            "longitude": place.longitude,
            "timezone": payload.get("timezone", place.timezone),
            "requested_days": days,
            "days": entries,
            "units": _units_for(self._units),
        }


def _at(sequence: Any, index: int) -> Any:
    if not isinstance(sequence, list) or index >= len(sequence):
        return None

    return sequence[index]
