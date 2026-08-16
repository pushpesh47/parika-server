"""
PARIKA Web Search Tool - Page Fetcher

Fetches a single web page and extracts its title, meta description,
and readable text content.
"""

from __future__ import annotations

from collections.abc import Callable
from time import sleep as time_sleep

from .exceptions import (
    InvalidPageUrlError,
    WebSearchNetworkError,
    WebSearchTimeoutError,
)
from .html_extraction import extract_meta_description, extract_text, extract_title
from .page_content import PageContent
from .retry import retry_with_backoff
from .transport import HttpTransport

_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    WebSearchTimeoutError,
    WebSearchNetworkError,
)


class PageFetcher:
    """
    Fetches web pages and extracts their readable content.

    PageFetcher applies the configured timeout and retry policy to
    every fetch and treats transient timeouts and network failures as
    retryable.
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
        Initialize the PageFetcher.

        Args:
            transport:
                HttpTransport used to issue the request.

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

    def fetch(self, url: str) -> PageContent:
        """
        Fetch a page and extract its content.

        Args:
            url:
                Absolute URL to fetch.

        Returns:
            The extracted PageContent.

        Raises:
            InvalidPageUrlError:
                If `url` is empty or not a string.

            WebSearchTimeoutError:
                If every attempt times out.

            WebSearchNetworkError:
                If every attempt fails for another network reason.
        """

        if not isinstance(url, str) or not url.strip():
            raise InvalidPageUrlError("url must be a non-empty string.")

        response = retry_with_backoff(
            lambda: self._transport.get(
                url,
                timeout=self._timeout_seconds,
            ),
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff_seconds,
            retryable_exceptions=_RETRYABLE_EXCEPTIONS,
            sleep=self._sleep,
        )

        body_text = response.body.decode("utf-8", errors="replace")

        return PageContent(
            url=url,
            final_url=response.url,
            status_code=response.status_code,
            title=extract_title(body_text),
            description=extract_meta_description(body_text),
            text=extract_text(body_text),
            content_type=response.headers.get("Content-Type"),
            content_length=len(response.body),
        )
