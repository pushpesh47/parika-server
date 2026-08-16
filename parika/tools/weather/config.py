"""
PARIKA Weather Tool - Configuration

Reads the `[weather]` TOML section through the existing
`Configuration` Core component and exposes it as a small, typed,
read-only snapshot, following the same pattern as
`parika/tools/web_search/config.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

DEFAULT_UNITS = "metric"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.5
DEFAULT_FORECAST_DAYS = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class WeatherToolConfig:
    """
    Immutable, typed snapshot of `[weather]` configuration.
    """

    enabled: bool = True
    units: str = DEFAULT_UNITS
    """Either `"metric"` or `"imperial"`."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS
    default_forecast_days: int = DEFAULT_FORECAST_DAYS


def load_weather_config(
    configuration: Configuration | None,
) -> WeatherToolConfig:
    """
    Build a `WeatherToolConfig` snapshot from `Configuration`.

    Args:
        configuration:
            The Core `Configuration` component. When `None`, every
            value falls back to its built-in default.

    Returns:
        The resolved, immutable configuration snapshot.
    """

    if configuration is None:
        return WeatherToolConfig()

    return WeatherToolConfig(
        enabled=bool(configuration.get("weather.enabled", True)),
        units=str(configuration.get("weather.units", DEFAULT_UNITS)),
        timeout_seconds=float(
            configuration.get(
                "weather.request_timeout_seconds", DEFAULT_TIMEOUT_SECONDS
            )
        ),
        max_attempts=int(
            configuration.get("weather.max_attempts", DEFAULT_MAX_ATTEMPTS)
        ),
        backoff_seconds=float(
            configuration.get("weather.backoff_seconds", DEFAULT_BACKOFF_SECONDS)
        ),
        default_forecast_days=int(
            configuration.get(
                "weather.default_forecast_days", DEFAULT_FORECAST_DAYS
            )
        ),
    )
