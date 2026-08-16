"""
PARIKA News Tool - Driver

Implements the `ToolDriver` contract for the `news.latest`,
`news.search`, and `news.topic` Capabilities.

A single `NewsToolDriver` instance is bound to exactly one `NewsMode`
at construction time (see `manifest.py`'s module docstring). The News
Module constructs three instances - one per Capability - and
registers each as its own Tool.

Every feed fetch goes through `feed_reader.fetch_feed()`. Fetching
several configured feeds for one request (`news.latest`/
`news.topic`) tolerates individual feed failures - a single
unreachable feed is logged and skipped, not a hard failure - and only
raises when *every* feed for that request failed.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from parika.core.logger.logger import Logger
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse

from .config import DEFAULT_MAX_RESULTS
from .exceptions import InvalidNewsArgumentError, NewsFeedError, NewsToolError
from .feed_reader import fetch_feed
from .feed_sources import GOOGLE_NEWS_SEARCH_ENDPOINT
from .manifest import NewsMode
from .news_item import NewsItem
from .transport import HttpTransport


def _item_to_dict(item: NewsItem) -> dict[str, Any]:
    return {
        "title": item.title,
        "link": item.link,
        "summary": item.summary,
        "source": item.source,
        "published": item.published,
        "published_at": item.published_at,
    }


def _sort_key(item: NewsItem) -> str:
    # Items without a parseable date sort last (empty string sorts
    # before any real ISO timestamp, so reverse=True naturally pushes
    # them to the end).
    return item.published_at or ""


class NewsToolDriver:
    """
    ToolDriver implementing one News Tool Capability.
    """

    def __init__(
        self,
        mode: NewsMode,
        *,
        transport: HttpTransport,
        latest_feeds: tuple[str, ...],
        topic_feeds: dict[str, tuple[str, ...]],
        default_max_results: int = DEFAULT_MAX_RESULTS,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        logger: Logger | None = None,
    ) -> None:
        """
        Initialize the driver for one Capability.

        Args:
            mode:
                Whether this instance implements `news.latest`,
                `news.search`, or `news.topic`.

            transport:
                HttpTransport used to fetch every feed.

            latest_feeds:
                Feeds used by `news.latest`.

            topic_feeds:
                Topic name (lowercased) -> feed URLs, used by
                `news.topic`.

            default_max_results:
                Default maximum number of items returned when the
                caller does not specify `max_results`.

            timeout_seconds, max_attempts, backoff_seconds:
                Network tuning applied to every feed fetch.

            logger:
                Optional PARIKA Logger, used to report individual
                feed failures at WARNING level without failing the
                whole request.
        """

        self._mode = mode
        self._transport = transport
        self._latest_feeds = latest_feeds
        self._topic_feeds = topic_feeds
        self._default_max_results = default_max_results
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._logger = logger.get_logger(__name__) if logger else None

    def execute(self, request: ToolRequest) -> ToolResponse:
        """
        Execute this driver's bound Capability.

        Expected `request.arguments`:
            query (str):
                Required for `news.search`: free-text search query.

            topic (str):
                Required for `news.topic`: a topic name (e.g.
                "technology"). Matched case-insensitively against
                configured `[news].feeds` topics; falls back to
                `news.search` semantics for an unrecognized topic.

            max_results (int):
                Optional maximum number of items returned. Defaults
                to `default_max_results`.

        Raises:
            InvalidNewsArgumentError:
                If a required argument is missing or invalid.

            NewsFeedError:
                If every feed for this request failed to fetch or
                parse.
        """

        raw_max_results: Any = request.arguments.get(
            "max_results", self._default_max_results
        )
        max_results = max(1, int(raw_max_results))

        if self._mode is NewsMode.LATEST:
            items = self._fetch_many(self._latest_feeds)
        elif self._mode is NewsMode.SEARCH:
            query = request.arguments.get("query")

            if not isinstance(query, str) or not query.strip():
                raise InvalidNewsArgumentError(
                    "request.arguments['query'] must be a non-empty "
                    "string."
                )

            items = self._search(query)
        else:
            topic = request.arguments.get("topic")

            if not isinstance(topic, str) or not topic.strip():
                raise InvalidNewsArgumentError(
                    "request.arguments['topic'] must be a non-empty "
                    "string."
                )

            feeds = self._topic_feeds.get(topic.strip().lower())

            if feeds:
                items = self._fetch_many(feeds)
            else:
                # No dedicated feed for this topic - fall back to a
                # general search for the topic text itself. This is
                # the News Tool's own data-driven behavior, not a
                # Planner-level "if topic == ..." routing shortcut.
                items = self._search(topic)

        sorted_items = tuple(
            sorted(items, key=_sort_key, reverse=True)
        )[:max_results]

        return ToolResponse(
            result=tuple(_item_to_dict(item) for item in sorted_items),
            attributes={"result_count": len(sorted_items)},
        )

    def _fetch_many(self, feed_urls: tuple[str, ...]) -> tuple[NewsItem, ...]:
        items: list[NewsItem] = []
        failures: list[str] = []

        for url in feed_urls:
            try:
                items.extend(
                    fetch_feed(
                        url,
                        transport=self._transport,
                        timeout_seconds=self._timeout_seconds,
                        max_attempts=self._max_attempts,
                        backoff_seconds=self._backoff_seconds,
                    )
                )
            except NewsToolError as ex:
                failures.append(f"{url}: {ex}")

                if self._logger is not None:
                    self._logger.warning(
                        "News feed '%s' failed (%s); skipping it.",
                        url,
                        ex,
                    )

        if not items and failures:
            raise NewsFeedError(
                "Every configured feed failed: " + "; ".join(failures)
            )

        return tuple(items)

    def _search(self, query: str) -> tuple[NewsItem, ...]:
        url = (
            f"{GOOGLE_NEWS_SEARCH_ENDPOINT}?"
            f"{urlencode({'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})}"
        )

        return fetch_feed(
            url,
            transport=self._transport,
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
        )
