"""
Unit tests for `parika.tools.web_search.config`.
"""

from __future__ import annotations

from parika.core.configuration.configuration import Configuration
from parika.tools.web_search.config import (
    DEFAULT_PROVIDER_ORDER,
    WebSearchProviderConfig,
    load_web_search_config,
)


class TestLoadWebSearchConfig:
    def test_none_configuration_returns_built_in_defaults(self) -> None:
        config = load_web_search_config(None)

        assert config == WebSearchProviderConfig()
        assert config.enabled is True
        assert config.default_provider == "google"
        assert config.provider_order == DEFAULT_PROVIDER_ORDER
        assert config.google_cse_api_key == ""
        assert config.google_cse_search_engine_id == ""

    def test_reads_web_search_section(self) -> None:
        configuration = Configuration()
        configuration._config = {
            "web_search": {
                "enabled": True,
                "default_provider": "bing",
                "provider_order": ["bing", "duckduckgo", "google"],
            }
        }
        configuration._is_loaded = True

        config = load_web_search_config(configuration)

        assert config.enabled is True
        assert config.default_provider == "bing"
        assert config.provider_order == ("bing", "duckduckgo", "google")

    def test_reads_google_cse_section(self) -> None:
        configuration = Configuration()
        configuration._config = {
            "web_search": {
                "google_cse": {
                    "api_key": "test-key",
                    "search_engine_id": "test-cx",
                }
            }
        }
        configuration._is_loaded = True

        config = load_web_search_config(configuration)

        assert config.google_cse_api_key == "test-key"
        assert config.google_cse_search_engine_id == "test-cx"

    def test_disabled_flag_is_read(self) -> None:
        configuration = Configuration()
        configuration._config = {"web_search": {"enabled": False}}
        configuration._is_loaded = True

        config = load_web_search_config(configuration)

        assert config.enabled is False

    def test_validation_defaults_are_applied_when_none_configured(
        self,
    ) -> None:
        config = load_web_search_config(None)

        assert config.validation_enabled is True
        assert config.validation_min_confidence == 0.15
        assert config.validation_max_retries == 1
        assert config.validation_title_weight == 0.5
        assert config.validation_snippet_weight == 0.3
        assert config.validation_url_weight == 0.2

    def test_reads_validation_section(self) -> None:
        configuration = Configuration()
        configuration._config = {
            "web_search": {
                "validation_enabled": False,
                "validation_min_confidence": 0.5,
                "validation_max_retries": 2,
                "validation_title_weight": 1.0,
                "validation_snippet_weight": 0.5,
                "validation_url_weight": 0.1,
            }
        }
        configuration._is_loaded = True

        config = load_web_search_config(configuration)

        assert config.validation_enabled is False
        assert config.validation_min_confidence == 0.5
        assert config.validation_max_retries == 2
        assert config.validation_title_weight == 1.0
        assert config.validation_snippet_weight == 0.5
        assert config.validation_url_weight == 0.1

    def test_missing_section_falls_back_to_defaults(self) -> None:
        configuration = Configuration()
        configuration._config = {}
        configuration._is_loaded = True

        config = load_web_search_config(configuration)

        assert config == WebSearchProviderConfig()


class TestFailoverOrder:
    def test_default_provider_comes_first(self) -> None:
        config = WebSearchProviderConfig(
            default_provider="bing",
            provider_order=("duckduckgo", "google", "bing"),
        )

        assert config.failover_order() == ("bing", "duckduckgo", "google")

    def test_default_provider_not_duplicated_when_also_listed(self) -> None:
        config = WebSearchProviderConfig(
            default_provider="google",
            provider_order=("google", "duckduckgo", "bing"),
        )

        assert config.failover_order() == ("google", "duckduckgo", "bing")

    def test_single_provider(self) -> None:
        config = WebSearchProviderConfig(
            default_provider="duckduckgo", provider_order=("duckduckgo",)
        )

        assert config.failover_order() == ("duckduckgo",)

    def test_explicit_multi_provider_order_covers_every_implemented_provider(
        self,
    ) -> None:
        """
        `config/defaults.toml`'s real `[web_search].provider_order`
        (not `WebSearchProviderConfig()`'s own bare, single-provider
        dataclass default - see `DEFAULT_PROVIDER_ORDER`'s docstring)
        is what actually spans every implemented provider in
        production.
        """

        config = WebSearchProviderConfig(
            default_provider="google",
            provider_order=(
                "google",
                "bing",
                "duckduckgo",
                "mojeek",
                "qwant",
                "google_cse",
            ),
        )

        assert config.failover_order() == (
            "google",
            "bing",
            "duckduckgo",
            "mojeek",
            "qwant",
            "google_cse",
        )
