"""
Unit tests for NewsToolDriver.
"""

from __future__ import annotations

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.tools.news.driver import NewsToolDriver
from parika.tools.news.exceptions import InvalidNewsArgumentError, NewsFeedError
from parika.tools.news.manifest import NewsMode
from parika.tools.news.transport import HttpResponse

FEED_OLD = """<?xml version="1.0"?><rss version="2.0"><channel><title>A</title>
<item><title>Old</title><link>https://a.example/1</link><description>o</description>
<pubDate>Wed, 01 Jul 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

FEED_NEW = """<?xml version="1.0"?><rss version="2.0"><channel><title>B</title>
<item><title>New</title><link>https://b.example/1</link><description>n</description>
<pubDate>Thu, 30 Jul 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


class _FakeTransport:
    def __init__(self, *, feeds: dict[str, bytes] | None = None) -> None:
        self._feeds = feeds or {}
        self.calls: list[str] = []
        self.fail_urls: set[str] = set()

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        self.calls.append(url)

        if url in self.fail_urls:
            return HttpResponse(status_code=500, url=url, headers={}, body=b"err")

        for key, body in self._feeds.items():
            if key in url:
                return HttpResponse(status_code=200, url=url, headers={}, body=body)

        return HttpResponse(status_code=200, url=url, headers={}, body=FEED_NEW.encode())


def _driver(mode: NewsMode, transport, **kwargs) -> NewsToolDriver:  # noqa: ANN001
    return NewsToolDriver(
        mode,
        transport=transport,
        latest_feeds=kwargs.pop("latest_feeds", ("https://a.example/feed", "https://b.example/feed")),
        topic_feeds=kwargs.pop(
            "topic_feeds", {"technology": ("https://tech.example/feed",)}
        ),
        max_attempts=1,
        backoff_seconds=0.0,
        **kwargs,
    )


class TestLatest:
    def test_aggregates_and_sorts_by_recency(self) -> None:
        transport = _FakeTransport(
            feeds={"a.example": FEED_OLD.encode(), "b.example": FEED_NEW.encode()}
        )
        driver = _driver(NewsMode.LATEST, transport)

        response = driver.execute(ToolRequest(arguments={}))

        assert response.result[0]["title"] == "New"
        assert response.result[1]["title"] == "Old"

    def test_partial_feed_failure_is_tolerated(self) -> None:
        transport = _FakeTransport(feeds={"b.example": FEED_NEW.encode()})
        transport.fail_urls.add("https://a.example/feed")

        driver = _driver(NewsMode.LATEST, transport)
        response = driver.execute(ToolRequest(arguments={}))

        assert len(response.result) == 1
        assert response.result[0]["title"] == "New"

    def test_every_feed_failing_raises(self) -> None:
        transport = _FakeTransport()
        transport.fail_urls.update(
            {"https://a.example/feed", "https://b.example/feed"}
        )

        driver = _driver(NewsMode.LATEST, transport)

        with pytest.raises(NewsFeedError):
            driver.execute(ToolRequest(arguments={}))

    def test_respects_max_results(self) -> None:
        transport = _FakeTransport(
            feeds={"a.example": FEED_OLD.encode(), "b.example": FEED_NEW.encode()}
        )
        driver = _driver(NewsMode.LATEST, transport)

        response = driver.execute(ToolRequest(arguments={"max_results": 1}))

        assert len(response.result) == 1
        assert response.result[0]["title"] == "New"


class TestSearch:
    def test_requires_query(self) -> None:
        driver = _driver(NewsMode.SEARCH, _FakeTransport())

        with pytest.raises(InvalidNewsArgumentError):
            driver.execute(ToolRequest(arguments={}))

    def test_builds_google_news_search_url(self) -> None:
        transport = _FakeTransport()
        driver = _driver(NewsMode.SEARCH, transport)

        driver.execute(ToolRequest(arguments={"query": "parika"}))

        assert "news.google.com/rss/search" in transport.calls[0]
        assert "q=parika" in transport.calls[0]


class TestTopic:
    def test_known_topic_uses_configured_feed(self) -> None:
        transport = _FakeTransport(feeds={"tech.example": FEED_NEW.encode()})
        driver = _driver(NewsMode.TOPIC, transport)

        response = driver.execute(ToolRequest(arguments={"topic": "Technology"}))

        assert "tech.example" in transport.calls[0]
        assert response.result[0]["title"] == "New"

    def test_unknown_topic_falls_back_to_search(self) -> None:
        transport = _FakeTransport()
        driver = _driver(NewsMode.TOPIC, transport)

        driver.execute(ToolRequest(arguments={"topic": "astrology"}))

        assert "news.google.com/rss/search" in transport.calls[0]
        assert "q=astrology" in transport.calls[0]

    def test_requires_topic(self) -> None:
        driver = _driver(NewsMode.TOPIC, _FakeTransport())

        with pytest.raises(InvalidNewsArgumentError):
            driver.execute(ToolRequest(arguments={}))
