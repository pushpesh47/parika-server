"""
Unit tests for `parika.tools.news.feed_reader`.
"""

from __future__ import annotations

import pytest

from parika.tools.news.exceptions import NewsNetworkError
from parika.tools.news.feed_reader import fetch_feed
from parika.tools.news.transport import HttpResponse

VALID_RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<title>Example Feed</title>
<item>
  <title>Item One</title>
  <link>https://example.com/1</link>
  <description>Summary one.</description>
  <pubDate>Wed, 30 Jul 2026 10:00:00 GMT</pubDate>
</item>
</channel></rss>"""

MALFORMED_RSS = "<rss><channel><title>Broken</channel>"


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


class TestFetchFeed:
    def test_parses_valid_feed(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(VALID_RSS.encode())

        items = fetch_feed(
            "https://example.com/feed.xml",
            transport=transport,
            timeout_seconds=5.0,
            max_attempts=1,
            backoff_seconds=0.0,
        )

        assert len(items) == 1
        assert items[0].title == "Item One"
        assert items[0].link == "https://example.com/1"
        assert items[0].source == "Example Feed"
        assert items[0].published_at is not None

    def test_tolerates_malformed_feed(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(MALFORMED_RSS.encode())

        # feedparser is deliberately tolerant - malformed input should
        # not raise, it should just parse what it can (possibly zero
        # entries).
        items = fetch_feed(
            "https://example.com/feed.xml",
            transport=transport,
            timeout_seconds=5.0,
            max_attempts=1,
            backoff_seconds=0.0,
        )
        assert isinstance(items, tuple)

    def test_http_error_raises(self) -> None:
        transport = _FakeTransport()
        transport.queue_response(b"error", status_code=500)

        with pytest.raises(NewsNetworkError):
            fetch_feed(
                "https://example.com/feed.xml",
                transport=transport,
                timeout_seconds=5.0,
                max_attempts=1,
                backoff_seconds=0.0,
            )
