"""
Unit tests for WeatherToolDriver.
"""

from __future__ import annotations

import json

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.tools.weather.driver import WeatherToolDriver
from parika.tools.weather.exceptions import (
    InvalidWeatherArgumentError,
    LocationNotFoundError,
)
from parika.tools.weather.manifest import WeatherMode
from parika.tools.weather.transport import HttpResponse

GEOCODE_BODY = json.dumps(
    {
        "results": [
            {
                "name": "Bengaluru",
                "latitude": 12.97,
                "longitude": 77.59,
                "country": "India",
                "timezone": "Asia/Kolkata",
            }
        ]
    }
).encode()

CURRENT_BODY = json.dumps(
    {
        "timezone": "Asia/Kolkata",
        "current": {
            "time": "2026-07-30T12:00",
            "temperature_2m": 28.5,
            "relative_humidity_2m": 60,
            "apparent_temperature": 30.1,
            "precipitation": 0.0,
            "weather_code": 1,
            "wind_speed_10m": 10.2,
            "wind_direction_10m": 180,
            "is_day": 1,
        },
    }
).encode()

FORECAST_BODY = json.dumps(
    {
        "timezone": "Asia/Kolkata",
        "daily": {
            "time": ["2026-07-30", "2026-07-31"],
            "weather_code": [1, 61],
            "temperature_2m_max": [30, 29],
            "temperature_2m_min": [22, 21],
            "precipitation_sum": [0, 5],
            "wind_speed_10m_max": [15, 20],
        },
    }
).encode()


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._responses: list[HttpResponse | Exception] = []

    def queue_response(self, body: bytes, status_code: int = 200) -> None:
        self._responses.append(
            HttpResponse(status_code=status_code, url="", headers={}, body=body)
        )

    def queue_error(self, error: Exception) -> None:
        self._responses.append(error)

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        self.calls.append(url)
        item = self._responses.pop(0)

        if isinstance(item, Exception):
            raise item

        return item


class TestCurrentWeather:
    def test_returns_current_conditions(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(GEOCODE_BODY)
        transport.queue_response(CURRENT_BODY)

        driver = WeatherToolDriver(WeatherMode.CURRENT, transport=transport)
        response = driver.execute(
            ToolRequest(arguments={"location": "Bengaluru"})
        )

        assert response.result["location"] == "Bengaluru"
        assert response.result["temperature"] == 28.5
        assert response.result["description"] == "Mainly clear"

    def test_rejects_missing_location(self) -> None:
        transport = _FakeTransport()
        driver = WeatherToolDriver(WeatherMode.CURRENT, transport=transport)

        with pytest.raises(InvalidWeatherArgumentError):
            driver.execute(ToolRequest(arguments={}))

    def test_unresolvable_location_raises(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(json.dumps({"results": []}).encode())

        driver = WeatherToolDriver(WeatherMode.CURRENT, transport=transport)

        with pytest.raises(LocationNotFoundError):
            driver.execute(ToolRequest(arguments={"location": "Nowhere"}))


class TestForecastWeather:
    def test_returns_requested_number_of_days(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(GEOCODE_BODY)
        transport.queue_response(FORECAST_BODY)

        driver = WeatherToolDriver(WeatherMode.FORECAST, transport=transport)
        response = driver.execute(
            ToolRequest(arguments={"location": "Bengaluru", "days": 2})
        )

        assert response.result["requested_days"] == 2
        assert len(response.result["days"]) == 2
        assert response.result["days"][1]["description"] == "Slight rain"

    def test_days_argument_is_clamped(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(GEOCODE_BODY)
        transport.queue_response(FORECAST_BODY)

        driver = WeatherToolDriver(WeatherMode.FORECAST, transport=transport)
        driver.execute(
            ToolRequest(arguments={"location": "Bengaluru", "days": 999})
        )

        # forecast_days query param should be clamped to 16
        assert "forecast_days=16" in transport.calls[-1]


class TestImperialUnits:
    def test_imperial_units_map_to_fahrenheit(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(GEOCODE_BODY)
        transport.queue_response(CURRENT_BODY)

        driver = WeatherToolDriver(
            WeatherMode.CURRENT, transport=transport, units="imperial"
        )
        driver.execute(ToolRequest(arguments={"location": "Bengaluru"}))

        assert "temperature_unit=fahrenheit" in transport.calls[-1]
