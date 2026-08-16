"""
PARIKA News Tool package.

Implements the `news.latest`, `news.search`, and `news.topic`
Capabilities using RSS/Atom aggregation (via `feedparser`) of
no-API-key sources: curated major wire service/broadcaster feeds for
`news.latest`/`news.topic`, and Google News' public RSS search
endpoint for `news.search` and any unrecognized `news.topic` topic.

Public exports provide everything needed to register these Tools with
ToolManager, either directly or through the News Module.
"""

from __future__ import annotations

from .config import NewsToolConfig, load_news_config
from .driver import NewsToolDriver
from .exceptions import (
    InvalidNewsArgumentError,
    NewsFeedError,
    NewsNetworkError,
    NewsTimeoutError,
    NewsToolError,
)
from .feed_reader import fetch_feed
from .feed_sources import (
    DEFAULT_LATEST_FEEDS,
    DEFAULT_TOPIC_FEEDS,
    GOOGLE_NEWS_SEARCH_ENDPOINT,
)
from .manifest import (
    NEWS_CAPABILITY_LATEST,
    NEWS_CAPABILITY_SEARCH,
    NEWS_CAPABILITY_TOPIC,
    NEWS_TOOL_ID_LATEST,
    NEWS_TOOL_ID_SEARCH,
    NEWS_TOOL_ID_TOPIC,
    NEWS_TOOL_VERSION,
    NewsMode,
    create_news_latest_tool,
    create_news_search_tool,
    create_news_topic_tool,
)
from .news_item import NewsItem
from .transport import HttpResponse, HttpTransport, UrllibHttpTransport

__all__ = [
    "DEFAULT_LATEST_FEEDS",
    "DEFAULT_TOPIC_FEEDS",
    "GOOGLE_NEWS_SEARCH_ENDPOINT",
    "NEWS_CAPABILITY_LATEST",
    "NEWS_CAPABILITY_SEARCH",
    "NEWS_CAPABILITY_TOPIC",
    "NEWS_TOOL_ID_LATEST",
    "NEWS_TOOL_ID_SEARCH",
    "NEWS_TOOL_ID_TOPIC",
    "NEWS_TOOL_VERSION",
    "HttpResponse",
    "HttpTransport",
    "InvalidNewsArgumentError",
    "NewsFeedError",
    "NewsItem",
    "NewsMode",
    "NewsNetworkError",
    "NewsTimeoutError",
    "NewsToolConfig",
    "NewsToolDriver",
    "NewsToolError",
    "UrllibHttpTransport",
    "create_news_latest_tool",
    "create_news_search_tool",
    "create_news_topic_tool",
    "fetch_feed",
    "load_news_config",
]
