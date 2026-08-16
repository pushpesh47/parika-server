"""
PARIKA Web Search Tool - Google Search Backend (HTML)

A `SearchBackend` implementation backed by Google's public HTML
search results page. Requires no configuration and is always
considered available (see `provider_registry.py`) - unlike
`search_backend_google_cse.py`, which uses Google's official, paid
Custom Search JSON API and does require credentials.

Like the other HTML-scraping backends, this requires no API key and
parses the returned HTML using only the Python standard library.
Google's result markup is both more variable and more aggressively
obfuscated than DuckDuckGo's, Bing's, Mojeek's, or Qwant's, and Google
is also more likely to serve a CAPTCHA/consent page to automated
clients; this backend is therefore explicitly a best-effort
implementation, exactly like `search_backend_duckduckgo.py`'s own
documented anti-bot caveat. When it stops matching Google's current
markup (or is consistently challenged), failover to another configured
provider - not a code change here - is the intended remedy; see
`config.py` and `provider_registry.py`.
"""

from __future__ import annotations
import logging
from collections.abc import Callable
from html.parser import HTMLParser
from time import sleep as time_sleep
from urllib.parse import parse_qs, quote_plus, urlparse

from .backend_support import (
    decode_body,
    fetch_with_retry,
    raise_if_blocked,
    raise_if_http_error,
    validate_search_arguments,
)
from .search_result import SearchResult
from .transport import HttpTransport

GOOGLE_HTML_ENDPOINT = "https://www.google.com/search?q={query}&num={max_results}"

_BLOCKED_INDICATORS = (
    "our systems have detected unusual traffic",
    "recaptcha",
)
"""
Google serves a CAPTCHA/consent page instead of results when it
suspects automated traffic.
"""

_logger = logging.getLogger(__name__)

def _unwrap_google_redirect(href: str) -> str:
    """
    Resolve a Google `/url?q=<url>` redirect into the real target
    URL. When `href` does not match that pattern, it is returned
    unchanged.
    """

    if not href:
        return href

    if not href.startswith("/url") and not href.startswith("http"):
        return href

    parsed = urlparse(href)

    if parsed.path != "/url":
        return href

    target = parse_qs(parsed.query).get("q")

    if not target:
        return href

    return target[0]


_KNOWN_SNIPPET_CLASSES = frozenset({"VwiC3b", "yXK7lf", "MUxGbd"})
"""
Class names Google has used for a result's snippet `<div>` at
various points; checked as a first-priority signal when present, but
never required - see `_GoogleResultParser`'s docstring for why.
"""

_FALLBACK_SNIPPET_MAX_LENGTH = 500
"""
Upper bound on the best-effort fallback snippet text (§ collected when
no known snippet class is found) to avoid accumulating unrelated
trailing page text (sitelinks, "Cached", related searches, ...) into
an unbounded string.
"""

_IGNORED_HREF_PREFIXES = (
    "#",
    "javascript:",
    "/search",
    "/preferences",
    "/advanced_search",
    "/setprefs",
    "/url?q=/search",
)
"""
Google's own UI/navigation links (pagination, "Search tools", account
menus, ...) that must never be mistaken for a result's link, even
though they are ordinary `<a>` tags too.
"""


class _GoogleResultParser(HTMLParser):
    """
    Extracts search results from a Google HTML results page.

    Google frequently renames the CSS classes wrapping each organic
    result (`g`, `MjjYud`, `yuRUbf`, `zReHs`, ... have all been used
    at different times, sometimes for the very same layout) and has
    increasingly moved to dynamically generated, non-semantic class
    names - which is exactly why a class-name-anchored parser
    eventually parses zero results the moment Google ships a markup
    change, without any actual loss of the data itself.

    This parser instead relies on the one structural fact that has
    remained true across every Google layout variant: every organic
    result's title is rendered as an `<h3>` immediately preceded by -
    or wrapped by - the `<a href="...">` that links to it. Tracking
    "the most recently opened anchor with a real destination href" and
    pairing it with the next `<h3>` is therefore far more resilient to
    markup churn than matching any specific container class, while
    still preferring known snippet class names
    (`_KNOWN_SNIPPET_CLASSES`) when they happen to be present, as a
    fast, precise first choice.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        self.results: list[dict[str, str]] = []

        self._last_anchor_url: str | None = None
        self._in_title = False
        self._title_captured = False
        self._pending_url: str | None = None
        self._pending_title_chunks: list[str] = []
        self._pending_snippet_chunks: list[str] = []
        self._in_known_snippet = False
        self._known_snippet_captured = False
        self._collecting_fallback_snippet = False
        self._fallback_snippet_chunks: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:

        attributes = dict(attrs)

        if tag == "a":
            href = attributes.get("href") or ""

            if href and not any(
                href.startswith(prefix) for prefix in _IGNORED_HREF_PREFIXES
            ):
                self._last_anchor_url = _unwrap_google_redirect(href)

            return

        if tag == "h3":
            self._flush_pending()
            self._pending_url = self._last_anchor_url
            self._in_title = True
            self._title_captured = False
            self._collecting_fallback_snippet = False
            return

        if not self._pending_url or self._known_snippet_captured:
            return

        classes = (attributes.get("class") or "").split()

        if tag == "div" and any(
            klass in _KNOWN_SNIPPET_CLASSES for klass in classes
        ):
            self._in_known_snippet = True
            self._collecting_fallback_snippet = False

    def handle_endtag(self, tag: str) -> None:

        if tag == "h3" and self._in_title:
            self._in_title = False
            self._title_captured = True
            self._collecting_fallback_snippet = True

        elif tag == "div" and self._in_known_snippet:
            self._in_known_snippet = False
            self._known_snippet_captured = True
            self._collecting_fallback_snippet = False

    def handle_data(self, data: str) -> None:

        if self._in_title:
            self._pending_title_chunks.append(data)
            return

        if self._in_known_snippet:
            self._pending_snippet_chunks.append(data)
            return

        if (
            self._collecting_fallback_snippet
            and self._pending_url
            and len(self._fallback_snippet_text()) < _FALLBACK_SNIPPET_MAX_LENGTH
        ):
            self._fallback_snippet_chunks.append(data)

    def close(self) -> None:
        self._flush_pending()
        super().close()

    def _fallback_snippet_text(self) -> str:
        return "".join(self._fallback_snippet_chunks).strip()

    def _flush_pending(self) -> None:

        title = "".join(self._pending_title_chunks).strip()

        if title and self._pending_url:
            snippet = "".join(self._pending_snippet_chunks).strip()

            if not snippet:
                snippet = self._fallback_snippet_text()

            self.results.append(
                {
                    "title": title,
                    "url": self._pending_url,
                    "snippet": snippet,
                }
            )

        self._in_title = False
        self._title_captured = False
        self._pending_url = None
        self._pending_title_chunks = []
        self._pending_snippet_chunks = []
        self._in_known_snippet = False
        self._known_snippet_captured = False
        self._collecting_fallback_snippet = False
        self._fallback_snippet_chunks = []


class GoogleHtmlSearchBackend:
    """
    SearchBackend implementation using Google's HTML results endpoint.

    This endpoint requires no API key. Results are parsed directly
    from the returned HTML using only the Python standard library.
    See this module's docstring for this backend's best-effort
    caveats.
    """

    def __init__(
        self,
        transport: HttpTransport,
        *,
        timeout_seconds: float = 10.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time_sleep,
    ) -> None:
        """
        Initialize the search backend.

        Args:
            transport:
                HttpTransport used to issue the search request.

            timeout_seconds:
                Maximum time, in seconds, to wait for the request to
                complete.

            max_attempts:
                Maximum number of attempts, including the first.

            backoff_seconds:
                Base delay, in seconds, between retry attempts.

            sleep:
                Sleep function used between retry attempts.
        """

        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep

    def search(
        self,
        query: str,
        *,
        max_results: int,
    ) -> tuple[SearchResult, ...]:
        """
        Perform a web search using Google's HTML endpoint.

        Raises:
            InvalidSearchQueryError:
                If `query` is empty or `max_results` is not positive.

            WebSearchTimeoutError:
                If every attempt times out.

            WebSearchNetworkError:
                If every attempt fails for another network reason, a
                CAPTCHA/consent page is served, or Google responds
                with an HTTP error status.
        """

        validate_search_arguments(query, max_results)

        url = GOOGLE_HTML_ENDPOINT.format(
            query=quote_plus(query), max_results=max_results
        )

        response = fetch_with_retry(
            self._transport,
            url,
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
            sleep=self._sleep,
        )
        raise_if_http_error(response, provider_name="Google")

        body_text = decode_body(response)

        _logger.debug("First 5000 characters of Google response:")
        _logger.debug(body_text[:5000])

        raise_if_blocked(
            body_text,
            provider_name="Google",
            indicators=_BLOCKED_INDICATORS,
        )

        parser = _GoogleResultParser()
        parser.feed(body_text)
        parser.close()

        _logger.debug("========== GOOGLE SEARCH PARSER ==========")
        _logger.debug("Query: %s", query)
        _logger.debug("URL: %s", url)
        _logger.debug("HTML Size: %d bytes", len(body_text))
        _logger.debug("Parsed Results: %d", len(parser.results))

        for index, result in enumerate(parser.results, start=1):
            _logger.debug(
                "[%d] Title=%r | URL=%r | Snippet=%r",
                index,
                result["title"],
                result["url"],
                result["snippet"],
            )

        _logger.debug("==========================================")

        return tuple(
            SearchResult(
                title=result["title"],
                url=result["url"],
                snippet=result["snippet"] or None,
            )
        for result in parser.results[:max_results]
        )
