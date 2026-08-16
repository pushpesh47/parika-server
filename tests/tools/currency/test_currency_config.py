"""
Unit tests for `parika.tools.currency.config`.
"""

from __future__ import annotations

from parika.core.configuration.configuration import Configuration
from parika.tools.currency.config import load_currency_config


class TestLoadCurrencyConfig:
    def test_none_configuration_uses_defaults(self) -> None:
        config = load_currency_config(None)

        assert config.default_provider == "frankfurter"
        assert config.failover_order() == ("frankfurter", "open_er_api")

    def test_provider_order_override(self) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "currency": {
                "default_provider": "open_er_api",
                "provider_order": ["open_er_api", "frankfurter"],
            }
        }

        config = load_currency_config(configuration)

        assert config.failover_order() == ("open_er_api", "frankfurter")

    def test_disabled_flag_is_read(self) -> None:
        configuration = Configuration()
        configuration._config = {"currency": {"enabled": False}}  # noqa: SLF001

        config = load_currency_config(configuration)

        assert config.enabled is False
