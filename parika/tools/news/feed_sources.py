"""
PARIKA News Tool - Default Feed Sources

Curated, no-API-key RSS/Atom feeds used by `news.latest` and
`news.topic` when configuration does not override them (see
`config.load_news_config()`). Every feed listed here is a major wire
service or national broadcaster's own public RSS feed - no
third-party aggregator, no key, no scraping.

Operators may fully replace either table via `[news.latest_feeds]` /
`[news.feeds]` in configuration without any code change.
"""

from __future__ import annotations

from collections.abc import Mapping

DEFAULT_LATEST_FEEDS: tuple[str, ...] = (
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://www.npr.org/rss/rss.php?id=1001",
)
"""
General, no-topic-filter headline feeds used by `news.latest`.
"""

DEFAULT_TOPIC_FEEDS: Mapping[str, tuple[str, ...]] = {
    "world": ("https://feeds.bbci.co.uk/news/world/rss.xml",),
    "business": ("https://feeds.bbci.co.uk/news/business/rss.xml",),
    "technology": ("https://feeds.bbci.co.uk/news/technology/rss.xml",),
    "science": (
        "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    ),
    "health": ("https://feeds.bbci.co.uk/news/health/rss.xml",),
    "politics": ("https://feeds.bbci.co.uk/news/politics/rss.xml",),
    "sports": ("https://feeds.bbci.co.uk/sport/rss.xml",),
    "entertainment": (
        "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
    ),
}
"""
Feeds used by `news.topic` when the requested topic (matched
case-insensitively) has a configured entry. An unrecognized topic
falls back to `news.search` against that topic string (see
`driver.py`) rather than failing - this is ordinary data lookup
inside the News Tool's own implementation, not capability-selection
logic in Planner, which never inspects topic strings at all.
"""

GOOGLE_NEWS_SEARCH_ENDPOINT = "https://news.google.com/rss/search"
"""
Google News' public RSS search endpoint - keyless, returns a
standard RSS feed for an arbitrary free-text query, parsed with the
exact same `feedparser`-based `feed_reader.fetch_feed()` used for
every other feed. Backs `news.search`, and `news.topic`'s fallback
for a topic with no configured feed.
"""
