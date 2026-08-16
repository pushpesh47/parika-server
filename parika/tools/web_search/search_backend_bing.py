"""
PARIKA Web Search Tool - Bing Search Backend (HTML)

A `SearchBackend` implementation backed by Bing's public HTML search
results page. Requires no configuration and is always considered
available (see `provider_registry.py`).

Like the other HTML-scraping backends, this requires no API key and
parses the returned HTML using only the Python standard library. Bing
may change its markup at any time, which would require updating
`_BingResultParser`'s recognized class names - the same maintenance
trade-off `search_backend_duckduckgo.py` already accepts for the
equivalent reason.
"""

from __future__ import annotations
import base64
import logging
from collections.abc import Callable
from html.parser import HTMLParser
from time import sleep as time_sleep
from urllib.parse import parse_qs, quote_plus, urlparse

from .backend_support import (
    decode_body,
    fetch_with_retry,
    raise_if_http_error,
    validate_search_arguments,
)
from .search_result import SearchResult
from .transport import HttpTransport

logger = logging.getLogger(__name__)
BING_HTML_ENDPOINT = "https://www.bing.com/search?q={query}"

_REDIRECT_PATH_PREFIX = "/ck/a"
"""
Bing wraps many organic result links in a `bing.com/ck/a?...&u=...`
click-tracking redirect rather than the direct destination URL - see
`_decode_bing_redirect()`.
"""


def _decode_bing_redirect(href: str) -> str:
    """
    Decode a Bing `/ck/a?...&u=<encoded>` click-tracking redirect into
    its real destination URL.

    The `u` query parameter observed in practice is a short, fixed
    two-character version marker (`a1` at the time of writing)
    followed by the URL-safe Base64 encoding (unpadded) of the real
    destination URL. When `href` does not match this shape at all -
    or the payload cannot be decoded into a genuine URL - `href` is
    returned unchanged, so a future change to this encoding degrades
    gracefully to "still returns *a* working link" rather than
    raising.
    """

    if not href:
        return href

    parsed = urlparse(href)

    if parsed.netloc and "bing.com" not in parsed.netloc:
        return href

    if parsed.path != _REDIRECT_PATH_PREFIX:
        return href

    encoded_values = parse_qs(parsed.query).get("u")

    if not encoded_values:
        return href

    encoded = encoded_values[0]

    # Try stripping the known two-character version marker first, then
    # fall back to treating the whole value as the payload, in case a
    # future Bing revision drops or changes the marker.
    for candidate in (encoded[2:], encoded):
        padded = candidate + "=" * (-len(candidate) % 4)

        try:
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue

        if decoded.startswith("http"):
            return decoded

    return href


class _BingResultParser(HTMLParser):
    """
    Extracts search results from a Bing HTML results page.

    Bing's organic results are `<li class="b_algo">` blocks. The
    clickable title is specifically the anchor inside the block's
    `<h2>` - other anchors inside the same block (a leading
    site-name/favicon caption row, sitelinks, ...) are not the title
    and must not be captured as one, which is exactly the mistake
    that previously produced garbled titles like
    "ndtv.comhttps://www.ndtv.com \u203a latest" (breadcrumb text
    concatenated with the title). The breadcrumb-style display URL is
    captured separately from `<cite>`, and the snippet from the
    caption paragraph following the title.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        self.results: list[dict[str, str]] = []

        self._in_result = False
        self._in_h2 = False
        self._in_title_anchor = False
        self._in_cite = False
        self._in_snippet = False
        self._title_captured = False
        self._display_url_captured = False
        self._snippet_captured = False
        self._pending_url: str | None = None
        self._pending_title_chunks: list[str] = []
        self._pending_display_url_chunks: list[str] = []
        self._pending_snippet_chunks: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:

        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()

        if tag == "li" and "b_algo" in classes:
            self._flush_pending()
            self._in_result = True
            return

        if not self._in_result:
            return

        if tag == "h2":
            self._in_h2 = True
            return

        if (
            tag == "a"
            and self._in_h2
            and self._pending_url is None
        ):
            href = attributes.get("href") or ""

            if href:
                self._pending_url = _decode_bing_redirect(href)
                self._in_title_anchor = True

            return

        if tag == "cite" and not self._display_url_captured:
            self._in_cite = True
            return

        if (
            tag == "p"
            and self._title_captured
            and not self._snippet_captured
        ):
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:

        if tag == "h2":
            self._in_h2 = False

            if self._in_title_anchor:
                self._in_title_anchor = False
                self._title_captured = True

        elif tag == "cite" and self._in_cite:
            self._in_cite = False
            self._display_url_captured = True

        elif tag == "p" and self._in_snippet:
            self._in_snippet = False
            self._snippet_captured = True

        elif tag == "li" and self._in_result:
            self._flush_pending()
            self._in_result = False

    def handle_data(self, data: str) -> None:

        if self._in_title_anchor:
            self._pending_title_chunks.append(data)

        elif self._in_cite:
            self._pending_display_url_chunks.append(data)

        elif self._in_snippet:
            self._pending_snippet_chunks.append(data)

    def close(self) -> None:
        self._flush_pending()
        super().close()

    def _flush_pending(self) -> None:

        title = "".join(self._pending_title_chunks).strip()

        if title and self._pending_url:
            self.results.append(
                {
                    "title": title,
                    "url": self._pending_url,
                    "display_url": "".join(
                        self._pending_display_url_chunks
                    ).strip(),
                    "snippet": "".join(
                        self._pending_snippet_chunks
                    ).strip(),
                }
            )

        self._in_result = False
        self._in_h2 = False
        self._in_title_anchor = False
        self._in_cite = False
        self._in_snippet = False
        self._title_captured = False
        self._display_url_captured = False
        self._snippet_captured = False
        self._pending_url = None
        self._pending_title_chunks = []
        self._pending_display_url_chunks = []
        self._pending_snippet_chunks = []


class BingHtmlSearchBackend:
    """
    SearchBackend implementation using Bing's HTML results endpoint.

    This endpoint requires no API key. Results are parsed directly
    from the returned HTML using only the Python standard library.
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
        Perform a web search using Bing's HTML endpoint.

        Raises:
            InvalidSearchQueryError:
                If `query` is empty or `max_results` is not positive.

            WebSearchTimeoutError:
                If every attempt times out.

            WebSearchNetworkError:
                If every attempt fails for another network reason, or
                Bing responds with an HTTP error status.
        """

        validate_search_arguments(query, max_results)

        url = BING_HTML_ENDPOINT.format(query=quote_plus(query))

        response = fetch_with_retry(
            self._transport,
            url,
            timeout_seconds=self._timeout_seconds,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
            sleep=self._sleep,
        )
        raise_if_http_error(response, provider_name="Bing")

        body_text = decode_body(response)

        logger.debug("First 5000 characters of Bing response:")
        logger.debug(body_text[:5000])

        parser = _BingResultParser()
        parser.feed(body_text)
        parser.close()

        logger.debug("========== BING SEARCH PARSER ==========")
        logger.debug("Query: %s", query)
        logger.debug("URL: %s", url)
        logger.debug("HTML Size: %d bytes", len(body_text))
        logger.debug("Parsed Results: %d", len(parser.results))

        for index, result in enumerate(parser.results, start=1):
            logger.debug(
                "[%d] Title=%r | URL=%r | DisplayURL=%r | Snippet=%r",
                index,
                result["title"],
                result["url"],
                result["display_url"],
                result["snippet"],
            )

        logger.debug("========================================")

        return tuple(
            SearchResult(
                title=result["title"],
                url=result["url"],
                snippet=result["snippet"] or None,
                display_url=result["display_url"] or None,
            )
            for result in parser.results[:max_results]
        )
