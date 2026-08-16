"""
PARIKA News Tool - Feed Reader

Fetches a single RSS/Atom/RDF feed URL through this Tool's own
`HttpTransport` (with retry/backoff), then hands the already-fetched
bytes to `feedparser.parse()` for parsing.

`feedparser` (https://github.com/kurtmckee/feedparser, BSD-2-Clause)
is the one third-party dependency this Tool - and the News Module -
introduces (see `docs/architecture/Tools_Expansion_Phase1_Plan.md`
section 3.4): it is a mature, actively maintained, pure-Python parser
that tolerantly handles the real-world dialect variance across RSS
0.9x/1.0/2.0, Atom 0.3/1.0, and malformed feeds (the `bozo` flag) far
more robustly than a hand-rolled XML parser would, unlike the
stdlib-only HTML scraping approach `web_search` uses for search
result pages.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime
from time import sleep as time_sleep
from typing import Any

import feedparser  # type: ignore[import-untyped]

from .exceptions import NewsNetworkError, NewsTimeoutError
from .news_item import NewsItem
from .retry import retry_with_backoff
from .transport import HttpTransport

_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    NewsTimeoutError,
    NewsNetworkError,
)


def _struct_time_to_iso(struct_time: Any) -> str | None:
    if struct_time is None:
        return None

    try:
        timestamp = calendar.timegm(struct_time)
        return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _entry_to_news_item(entry: Any, *, fallback_source: str | None) -> NewsItem:
    source_title = None

    source = entry.get("source")
    if isinstance(source, dict):
        source_title = source.get("title")

    return NewsItem(
        title=str(entry.get("title", "")).strip() or "(untitled)",
        link=str(entry.get("link", "")),
        summary=entry.get("summary"),
        source=source_title or fallback_source,
        published=entry.get("published") or entry.get("updated"),
        published_at=_struct_time_to_iso(
            entry.get("published_parsed") or entry.get("updated_parsed")
        ),
    )


def fetch_feed(
    url: str,
    *,
    transport: HttpTransport,
    timeout_seconds: float,
    max_attempts: int,
    backoff_seconds: float,
    sleep: Any = time_sleep,
) -> tuple[NewsItem, ...]:
    """
    Fetch and parse a single feed URL.

    Args:
        url:
            Feed URL (RSS, Atom, or RDF).

        transport:
            HttpTransport used to fetch the raw feed bytes.

        timeout_seconds, max_attempts, backoff_seconds:
            Network tuning applied to the fetch.

    Returns:
        Every entry the feed contained, normalized to `NewsItem`.
        Malformed feeds (`feedparser`'s `bozo` flag) still return
        whatever entries could be tolerantly parsed, matching
        `feedparser`'s own designed tolerance - this function never
        raises solely because a feed was imperfectly well-formed.

    Raises:
        NewsTimeoutError:
            If every fetch attempt times out.

        NewsNetworkError:
            If every fetch attempt fails for another network reason,
            or the provider returns an HTTP error status.
    """

    def _get() -> bytes:
        response = transport.get(url, timeout=timeout_seconds)

        if response.status_code >= 400:
            raise NewsNetworkError(
                f"Feed '{url}' returned HTTP {response.status_code}."
            )

        return response.body

    body = retry_with_backoff(
        _get,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        retryable_exceptions=_RETRYABLE_EXCEPTIONS,
        sleep=sleep,
    )

    parsed = feedparser.parse(body)

    fallback_source = None
    feed_meta = getattr(parsed, "feed", None)
    if feed_meta is not None:
        fallback_source = feed_meta.get("title")

    return tuple(
        _entry_to_news_item(entry, fallback_source=fallback_source)
        for entry in parsed.entries
    )
