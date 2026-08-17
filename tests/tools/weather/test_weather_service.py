"""
Unit tests for WeatherService.
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch
from pathlib import Path

import pytest

from parika.tools.weather.service import WeatherService
from parika.tools.weather.transport import HttpResponse
from parika.tools.weather.exceptions import WeatherNetworkError, WeatherTimeoutError


@pytest.fixture
def mock_transport():
    return Mock()


@pytest.fixture
def mock_configuration():
    config = Mock()
    config.get.side_effect = lambda key, default=None: {
        "weather.enabled": True,
        "weather.units": "metric",
        "weather.request_timeout_seconds": 10.0,
        "weather.max_attempts": 3,
        "weather.backoff_seconds": 0.5,
        "weather.default_forecast_days": 5,
        "weather.cache_ttl_seconds": 1200.0,
    }.get(key, default)
    config.get_project_root.return_value = Path("/tmp")
    return config


@pytest.fixture
def mock_logger():
    logger = Mock()
    logger.get_logger.return_value = Mock()
    return logger


class TestWeatherService:

    def test_weather_code_to_icon_clear_day(self, mock_transport, mock_configuration, mock_logger):
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )
        assert service._weather_code_to_icon(0, True) == "clear-day"

    def test_weather_code_to_icon_clear_night(self, mock_transport, mock_configuration, mock_logger):
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )
        assert service._weather_code_to_icon(0, False) == "clear-night"

    def test_weather_code_to_icon_partly_cloudy_day(self, mock_transport, mock_configuration, mock_logger):
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )
        assert service._weather_code_to_icon(1, True) == "partly-cloudy-day"
        assert service._weather_code_to_icon(2, True) == "partly-cloudy-day"

    def test_weather_code_to_icon_cloudy(self, mock_transport, mock_configuration, mock_logger):
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )
        assert service._weather_code_to_icon(3, True) == "cloudy"

    def test_weather_code_to_icon_fog(self, mock_transport, mock_configuration, mock_logger):
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )
        assert service._weather_code_to_icon(45, True) == "fog"
        assert service._weather_code_to_icon(48, True) == "fog"

    def test_weather_code_to_icon_rain(self, mock_transport, mock_configuration, mock_logger):
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )
        for code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]:
            assert service._weather_code_to_icon(code, True) == "rain"

    def test_weather_code_to_icon_snow(self, mock_transport, mock_configuration, mock_logger):
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )
        for code in [71, 73, 75, 77, 85, 86]:
            assert service._weather_code_to_icon(code, True) == "snow"

    def test_weather_code_to_icon_thunderstorm(self, mock_transport, mock_configuration, mock_logger):
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )
        for code in [95, 96, 99]:
            assert service._weather_code_to_icon(code, True) == "thunderstorm"

    def test_weather_code_to_icon_unknown(self, mock_transport, mock_configuration, mock_logger):
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )
        assert service._weather_code_to_icon(999, True) == "cloudy"

    def test_normalize_current(self, mock_transport, mock_configuration, mock_logger):
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )

        payload = {
            "timezone": "Asia/Kolkata",
            "current": {
                "time": "2026-07-30T12:00",
                "temperature_2m": 28.5,
                "relative_humidity_2m": 60,
                "apparent_temperature": 30.1,
                "precipitation": 0.0,
                "rain": 0.0,
                "showers": 0.0,
                "snowfall": 0.0,
                "weather_code": 1,
                "cloud_cover": 20,
                "surface_pressure": 1013.25,
                "wind_speed_10m": 10.2,
                "wind_direction_10m": 180,
                "wind_gusts_10m": 15.5,
                "visibility": 10000,
                "is_day": 1,
            },
        }

        result = service._normalize_current(payload, 12.97, 77.59)

        assert result["temperature_c"] == 28.5
        assert result["feels_like_c"] == 30.1
        assert result["condition"] == "Mainly clear"
        assert result["weather_code"] == 1
        assert result["icon"] == "partly-cloudy-day"
        assert result["is_day"] is True
        assert result["humidity_percent"] == 60
        assert result["precipitation_mm"] == 0.0
        assert result["wind_speed_kmh"] == 10.2
        assert result["wind_direction_degrees"] == 180
        assert result["wind_gusts_kmh"] == 15.5
        assert result["cloud_cover_percent"] == 20
        assert result["pressure_hpa"] == 1013.25
        assert result["visibility_m"] == 10000
        assert result["observed_at"] == "2026-07-30T12:00"

    def test_normalize_forecast(self, mock_transport, mock_configuration, mock_logger):
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )

        payload = {
            "daily": {
                "time": ["2026-07-30", "2026-07-31"],
                "weather_code": [1, 61],
                "temperature_2m_max": [30, 29],
                "temperature_2m_min": [22, 21],
                "apparent_temperature_max": [31, 30],
                "apparent_temperature_min": [23, 22],
                "precipitation_probability_max": [10, 80],
                "precipitation_sum": [0, 5],
                "sunrise": ["06:00", "06:01"],
                "sunset": ["18:30", "18:29"],
            },
        }

        result = service._normalize_forecast(payload)

        assert len(result) == 2
        assert result[0]["date"] == "2026-07-30"
        assert result[0]["condition"] == "Mainly clear"
        assert result[0]["weather_code"] == 1
        assert result[0]["icon"] == "partly-cloudy-day"
        assert result[0]["temperature_max_c"] == 30
        assert result[0]["temperature_min_c"] == 22
        assert result[0]["precipitation_probability_percent"] == 10
        assert result[0]["precipitation_sum_mm"] == 0

        assert result[1]["date"] == "2026-07-31"
        assert result[1]["condition"] == "Slight rain"
        assert result[1]["weather_code"] == 61
        assert result[1]["icon"] == "rain"
        assert result[1]["temperature_max_c"] == 29
        assert result[1]["precipitation_probability_percent"] == 80
        assert result[1]["precipitation_sum_mm"] == 5


class TestProviderParameterRegression:
    """Regression tests ensuring Open-Meteo provider parameters are correct."""

    def test_provider_request_uses_surface_pressure_not_pressure(
        self, mock_transport, mock_configuration, mock_logger
    ):
        """Ensure _CURRENT_FIELDS uses surface_pressure, not pressure."""
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )

        # Inspect the generated params - current field should contain surface_pressure
        params = service._build_params(12.97, 77.59)
        current_fields = params["current"]

        # current_fields is a comma-separated string; check for exact field names
        field_list = current_fields.split(",")
        assert "surface_pressure" in field_list
        assert "pressure" not in field_list

    def test_surface_pressure_normalized_to_pressure_hpa(
        self, mock_transport, mock_configuration, mock_logger
    ):
        """Ensure surface_pressure from provider maps to pressure_hpa in API."""
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )

        payload = {
            "timezone": "UTC",
            "current": {
                "time": "2026-07-30T12:00",
                "surface_pressure": 1015.5,
            },
        }

        result = service._normalize_current(payload, 12.97, 77.59)
        assert result["pressure_hpa"] == 1015.5


class TestProviderErrorLogging:
    """Tests for Weather provider error logging."""

    @pytest.mark.asyncio
    async def test_http_400_logs_error_with_diagnostics(
        self, mock_transport, mock_configuration, mock_logger
    ):
        """HTTP 400 from Open-Meteo logs ERROR with provider diagnostics."""
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )

        mock_response = HttpResponse(
            status_code=400,
            url="https://api.open-meteo.com/v1/forecast?...",
            headers={},
            body=b'Data corrupted at path \'\'. Cannot initialize SurfacePressureAndHeightVariable from invalid String value: pressure',
        )
        mock_transport.get.return_value = mock_response

        with pytest.raises(WeatherNetworkError):
            await service._fetch_from_provider(24.0091136, 85.3803008)

        # Verify ERROR log was called with diagnostics
        mock_logger.get_logger.return_value.error.assert_called()
        call_args = mock_logger.get_logger.return_value.error.call_args[0][0]
        assert "Weather provider request failed" in call_args
        assert "provider=Open-Meteo" in call_args
        assert "status=400" in call_args
        assert "latitude=24.0091136" in call_args
        assert "longitude=85.3803008" in call_args
        assert "response=" in call_args

    @pytest.mark.asyncio
    async def test_network_timeout_logs_error_with_diagnostics(
        self, mock_transport, mock_configuration, mock_logger
    ):
        """Network timeout logs ERROR with provider diagnostics."""
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )

        mock_transport.get.side_effect = WeatherTimeoutError(
            "Request timed out after 10 seconds."
        )

        with pytest.raises(WeatherTimeoutError):
            await service._fetch_from_provider(24.0091136, 85.3803008)

        # Verify ERROR log was called with diagnostics
        mock_logger.get_logger.return_value.error.assert_called()
        call_args = mock_logger.get_logger.return_value.error.call_args[0][0]
        assert "Weather provider request timeout" in call_args
        assert "provider=Open-Meteo" in call_args
        assert "latitude=24.0091136" in call_args
        assert "longitude=85.3803008" in call_args
        assert "exception=WeatherTimeoutError" in call_args

    @pytest.mark.asyncio
    async def test_network_error_logs_error_with_diagnostics(
        self, mock_transport, mock_configuration, mock_logger
    ):
        """Network error (non-timeout) logs ERROR with provider diagnostics."""
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )

        mock_transport.get.side_effect = WeatherNetworkError(
            "Request failed: connection refused"
        )

        with pytest.raises(WeatherNetworkError):
            await service._fetch_from_provider(24.0091136, 85.3803008)

        # Verify ERROR log was called with diagnostics
        mock_logger.get_logger.return_value.error.assert_called()
        call_args = mock_logger.get_logger.return_value.error.call_args[0][0]
        assert "Weather provider request failed" in call_args
        assert "provider=Open-Meteo" in call_args
        assert "latitude=24.0091136" in call_args
        assert "longitude=85.3803008" in call_args

    @pytest.mark.asyncio
    async def test_malformed_json_response_logs_error(
        self, mock_transport, mock_configuration, mock_logger
    ):
        """Malformed JSON response logs ERROR with diagnostics."""
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )

        mock_response = HttpResponse(
            status_code=200,
            url="https://api.open-meteo.com/v1/forecast?...",
            headers={},
            body=b"not valid json",
        )
        mock_transport.get.return_value = mock_response

        with pytest.raises(WeatherNetworkError):
            await service._fetch_from_provider(24.0091136, 85.3803008)

        # Verify ERROR log was called with diagnostics
        mock_logger.get_logger.return_value.error.assert_called()
        call_args = mock_logger.get_logger.return_value.error.call_args[0][0]
        assert "Weather provider response malformed" in call_args
        assert "provider=Open-Meteo" in call_args
        assert "latitude=24.0091136" in call_args
        assert "longitude=85.3803008" in call_args

    @pytest.mark.asyncio
    async def test_missing_current_field_logs_error(
        self, mock_transport, mock_configuration, mock_logger
    ):
        """Response missing 'current' field logs ERROR with diagnostics."""
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )

        mock_response = HttpResponse(
            status_code=200,
            url="https://api.open-meteo.com/v1/forecast?...",
            headers={},
            body=b'{"timezone": "UTC", "daily": {}}',
        )
        mock_transport.get.return_value = mock_response

        with pytest.raises(WeatherNetworkError):
            await service._fetch_from_provider(24.0091136, 85.3803008)

        # Verify ERROR log was called with diagnostics
        mock_logger.get_logger.return_value.error.assert_called()
        call_args = mock_logger.get_logger.return_value.error.call_args[0][0]
        assert "Weather provider response missing required fields" in call_args
        assert "provider=Open-Meteo" in call_args
        assert "latitude=24.0091136" in call_args
        assert "longitude=85.3803008" in call_args


class TestSuccessAndCacheLogging:
    """Tests for success and cache logging at appropriate levels."""

    @pytest.mark.asyncio
    async def test_successful_provider_refresh_logs_debug(
        self, mock_transport, mock_configuration, mock_logger
    ):
        """Successful provider refresh logs at DEBUG level, not INFO."""
        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
        )

        mock_response = HttpResponse(
            status_code=200,
            url="https://api.open-meteo.com/v1/forecast?...",
            headers={},
            body=b'{"timezone": "UTC", "current": {"time": "2026-07-30T12:00", "surface_pressure": 1013.25}}',
        )
        mock_transport.get.return_value = mock_response

        await service._fetch_from_provider(12.97, 77.59)

        # Verify DEBUG log was called (not INFO)
        mock_logger.get_logger.return_value.debug.assert_called()
        call_args = mock_logger.get_logger.return_value.debug.call_args[0][0]
        assert "Weather provider refresh completed" in call_args
        assert "provider=Open-Meteo" in call_args
        assert "latitude=12.97" in call_args
        assert "longitude=77.59" in call_args

        # Ensure INFO was not called for success
        mock_logger.get_logger.return_value.info.assert_not_called()

    def test_cache_hit_logs_debug(
        self, mock_transport, mock_configuration, mock_logger
    ):
        """Cache hit logs at DEBUG level."""
        from parika.tools.weather.cache import WeatherCache

        mock_cache = Mock(spec=WeatherCache)
        
        async def mock_get_or_fetch(key, fetch_fn):
            return ({"metadata": {"cache_status": "fresh"}}, "fresh")
        
        mock_cache.get_or_fetch = mock_get_or_fetch

        service = WeatherService(
            configuration=mock_configuration,
            logger=mock_logger,
            transport=mock_transport,
            cache=mock_cache,
        )

        import asyncio
        asyncio.run(service.get_weather(12.97, 77.59))

        # Verify DEBUG log was called for cache hit
        mock_logger.get_logger.return_value.debug.assert_called()
        call_args = mock_logger.get_logger.return_value.debug.call_args[0][0]
        assert "Weather cache hit" in call_args
        assert "key=" in call_args