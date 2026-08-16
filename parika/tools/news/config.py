"""
PARIKA News Tool - Configuration

Reads the `[news]` TOML section through the existing `Configuration`
Core component and exposes it as a small, typed, read-only snapshot,
following the same pattern as `parika/tools/web_search/config.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from parika.core.configuration.configuration import Configuration

from .feed_sources import DEFAULT_LATEST_FEEDS, DEFAULT_TOPIC_FEEDS

DEFAULT_MAX_RESULTS = 10
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.5


@dataclass(frozen=True, slots=True, kw_only=True)
class NewsToolConfig:
    """
    Immutable, typed snapshot of `[news]` configuration.
    """

    enabled: bool = True
    default_max_results: int = DEFAULT_MAX_RESULTS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS

    latest_feeds: tuple[str, ...] = DEFAULT_LATEST_FEEDS
    topic_feeds: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_TOPIC_FEEDS)
    )


def load_news_config(configuration: Configuration | None) -> NewsToolConfig:
    """
    Build a `NewsToolConfig` snapshot from `Configuration`.

    Args:
        configuration:
            The Core `Configuration` component. When `None`, every
            value falls back to its built-in default - the curated
            feed list in `feed_sources.py`.

    Returns:
        The resolved, immutable configuration snapshot.
    """

    if configuration is None:
        return NewsToolConfig()

    raw_latest = configuration.get(
        "news.latest_feeds", list(DEFAULT_LATEST_FEEDS)
    )
    latest_feeds = (
        tuple(str(url) for url in raw_latest)
        if isinstance(raw_latest, (list, tuple))
        else DEFAULT_LATEST_FEEDS
    )

    raw_topics = configuration.get("news.feeds", dict(DEFAULT_TOPIC_FEEDS))
    topic_feeds: dict[str, tuple[str, ...]] = {}

    if isinstance(raw_topics, dict):
        for topic, urls in raw_topics.items():
            if isinstance(urls, (list, tuple)):
                topic_feeds[str(topic).lower()] = tuple(str(u) for u in urls)
    else:
        topic_feeds = dict(DEFAULT_TOPIC_FEEDS)

    return NewsToolConfig(
        enabled=bool(configuration.get("news.enabled", True)),
        default_max_results=int(
            configuration.get("news.default_max_results", DEFAULT_MAX_RESULTS)
        ),
        timeout_seconds=float(
            configuration.get(
                "news.feed_timeout_seconds", DEFAULT_TIMEOUT_SECONDS
            )
        ),
        max_attempts=int(
            configuration.get("news.max_attempts", DEFAULT_MAX_ATTEMPTS)
        ),
        backoff_seconds=float(
            configuration.get("news.backoff_seconds", DEFAULT_BACKOFF_SECONDS)
        ),
        latest_feeds=latest_feeds,
        topic_feeds=topic_feeds,
    )
