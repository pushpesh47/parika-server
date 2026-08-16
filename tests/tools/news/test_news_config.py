"""
Unit tests for `parika.tools.news.config`.
"""

from __future__ import annotations

from parika.core.configuration.configuration import Configuration
from parika.tools.news.config import load_news_config


class TestLoadNewsConfig:
    def test_none_configuration_uses_curated_defaults(self) -> None:
        config = load_news_config(None)

        assert len(config.latest_feeds) > 0
        assert "technology" in config.topic_feeds

    def test_feed_overrides_are_read(self) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "news": {
                "latest_feeds": ["https://custom.example/feed"],
                "feeds": {"custom": ["https://custom.example/topic"]},
            }
        }

        config = load_news_config(configuration)

        assert config.latest_feeds == ("https://custom.example/feed",)
        assert config.topic_feeds == {"custom": ("https://custom.example/topic",)}

    def test_disabled_flag_is_read(self) -> None:
        configuration = Configuration()
        configuration._config = {"news": {"enabled": False}}  # noqa: SLF001

        config = load_news_config(configuration)

        assert config.enabled is False
