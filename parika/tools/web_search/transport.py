"""
PARIKA Web Search Tool - HTTP Transport

Defines the HttpTransport contract used by the Web Search Tool to
issue outbound HTTP requests, together with the default
implementation built on the Python standard library.

Isolating transport behind a small protocol allows the search and
page-fetching logic to be exercised deterministically in tests without
depending on real network access, while the default implementation
remains a genuine, working HTTP client for production use.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .exceptions import WebSearchNetworkError, WebSearchTimeoutError

DEFAULT_USER_AGENT = "PARIKA-WebSearchTool/1.0"


@dataclass(frozen=True, slots=True, kw_only=True)
class HttpResponse:
    """
    Immutable, normalized HTTP response.
    """

    status_code: int
    """HTTP status code."""

    url: str
    """Final URL after following redirects."""

    headers: Mapping[str, str]
    """Response headers."""

    body: bytes
    """Raw response body."""


@runtime_checkable
class HttpTransport(Protocol):
    """
    Protocol implemented by every HTTP transport usable by the Web
    Search Tool.
    """

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        """
        Perform an HTTP GET request.

        Args:
            url:
                Absolute URL to request.

            timeout:
                Maximum time, in seconds, to wait for the request to
                complete.

        Returns:
            The normalized HttpResponse.

        Raises:
            WebSearchTimeoutError:
                If the request exceeds `timeout`.

            WebSearchNetworkError:
                If the request fails for any other network reason.
        """
        ...

    def post(
        self,
        url: str,
        *,
        data: bytes | None,
        timeout: float,
        headers: Mapping[str, str],
    ) -> HttpResponse:
        """
        Perform an HTTP POST request.
        """
        ...


class UrllibHttpTransport:
    """
    Default HttpTransport implementation using the Python standard
    library's `urllib`.

    No third-party HTTP client dependency is introduced, in keeping
    with the project's standard-library-first preference.
    """

    def __init__(self, *, user_agent: str = DEFAULT_USER_AGENT) -> None:
        """
        Initialize the transport.

        Args:
            user_agent:
                User-Agent header sent with every request.
        """

        self._user_agent = user_agent

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        """
        Perform an HTTP GET request using `urllib.request`.
        """

        request = Request(
            url,
            headers={"User-Agent": self._user_agent},
            method="GET",
        )

        return self._perform_request(request, url=url, timeout=timeout)

    def post(
        self,
        url: str,
        *,
        data: bytes | None,
        timeout: float,
        headers: Mapping[str, str],
    ) -> HttpResponse:
        """
        Perform an HTTP POST request using `urllib.request`.
        """

        request_headers = {"User-Agent": self._user_agent}
        request_headers.update(headers)

        request = Request(
            url,
            data=data,
            headers=request_headers,
            method="POST",
        )

        return self._perform_request(request, url=url, timeout=timeout)

    def _perform_request(
        self,
        request: Request,
        *,
        url: str,
        timeout: float,
    ) -> HttpResponse:
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                body = response.read()
                status_code = response.status
                final_url = response.url
                headers = dict(response.headers.items())

        except HTTPError as ex:
            body = ex.read() if ex.fp is not None else b""

            return HttpResponse(
                status_code=ex.code,
                url=url,
                headers=dict(ex.headers.items()) if ex.headers else {},
                body=body,
            )

        except TimeoutError as ex:
            raise WebSearchTimeoutError(
                f"Request to '{url}' timed out after {timeout} seconds."
            ) from ex

        except URLError as ex:
            if isinstance(ex.reason, TimeoutError):
                raise WebSearchTimeoutError(
                    f"Request to '{url}' timed out after "
                    f"{timeout} seconds."
                ) from ex

            raise WebSearchNetworkError(
                f"Request to '{url}' failed: {ex.reason}"
            ) from ex

        return HttpResponse(
            status_code=status_code,
            url=final_url,
            headers=headers,
            body=body,
        )
