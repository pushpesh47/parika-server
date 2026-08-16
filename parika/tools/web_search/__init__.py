"""
PARIKA Web Search Tool package.

Implements the `web.search` Capability: searching the web and,
optionally, fetching and extracting the readable content of each
result page.

Public exports provide everything needed to register this Tool with
ToolManager, either directly or through the Web Search Module.
"""

from .dedup import DEFAULT_TITLE_SIMILARITY_THRESHOLD, deduplicate_results, normalize_url
from .driver import WebSearchToolDriver
from .exceptions import (
    InvalidPageUrlError,
    InvalidSearchQueryError,
    WebSearchAllProvidersFailedError,
    WebSearchNetworkError,
    WebSearchProviderUnavailableError,
    WebSearchTimeoutError,
    WebSearchToolError,
)
from .manifest import (
    WEB_SEARCH_CAPABILITY_ID,
    WEB_SEARCH_TOOL_ID,
    WEB_SEARCH_TOOL_VERSION,
    create_web_search_tool,
)
from .page_content import PageContent
from .page_fetcher import PageFetcher
from .protocol import SearchBackend
from .provider_registry import PROVIDER_REGISTRY, build_search_backend
from .search_backend_bing import BingHtmlSearchBackend
from .search_backend_duckduckgo import DuckDuckGoHtmlSearchBackend
from .search_backend_failover import FailoverSearchBackend
from .search_backend_google import GoogleHtmlSearchBackend
from .search_backend_google_cse import GoogleCseSearchBackend
from .search_backend_mojeek import MojeekHtmlSearchBackend
from .search_backend_parallel_mcp import ParallelMcpSearchBackend
from .search_backend_qwant import QwantHtmlSearchBackend
from .search_result import SearchResult
from .transport import HttpResponse, HttpTransport, UrllibHttpTransport

__all__ = [
    "BingHtmlSearchBackend",
    "DEFAULT_TITLE_SIMILARITY_THRESHOLD",
    "DuckDuckGoHtmlSearchBackend",
    "FailoverSearchBackend",
    "GoogleCseSearchBackend",
    "GoogleHtmlSearchBackend",
    "HttpResponse",
    "HttpTransport",
    "InvalidPageUrlError",
    "InvalidSearchQueryError",
    "MojeekHtmlSearchBackend",
    "PROVIDER_REGISTRY",
    "PageContent",
    "PageFetcher",
    "ParallelMcpSearchBackend",
    "QwantHtmlSearchBackend",
    "SearchBackend",
    "SearchResult",
    "UrllibHttpTransport",
    "WEB_SEARCH_CAPABILITY_ID",
    "WEB_SEARCH_TOOL_ID",
    "WEB_SEARCH_TOOL_VERSION",
    "WebSearchAllProvidersFailedError",
    "WebSearchNetworkError",
    "WebSearchProviderUnavailableError",
    "WebSearchTimeoutError",
    "WebSearchToolDriver",
    "WebSearchToolError",
    "build_search_backend",
    "create_web_search_tool",
    "deduplicate_results",
    "normalize_url",
]
