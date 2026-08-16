"""
Unit tests for `parika.tools.weather.config`.
"""

from __future__ import annotations

from parika.core.configuration.configuration import Configuration
from parika.tools.weather.config import load_weather_config


class TestLoadWeatherConfig:
    def test_none_configuration_uses_defaults(self) -> None:
        config = load_weather_config(None)

        assert config.enabled is True
        assert config.units == "metric"

    def test_units_override(self) -> None:
        configuration = Configuration()
        configuration._config = {"weather": {"units": "imperial"}}  # noqa: SLF001

        config = load_weather_config(configuration)

        assert config.units == "imperial"

    def test_disabled_flag_is_read(self) -> None:
        configuration = Configuration()
        configuration._config = {"weather": {"enabled": False}}  # noqa: SLF001

        config = load_weather_config(configuration)

        assert config.enabled is False
