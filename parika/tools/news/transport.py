"""
PARIKA News Tool - HTTP Transport

Defines the HttpTransport contract used by the News Tool to fetch raw
feed bytes, together with the default implementation built on the
Python standard library.

The News Tool deliberately fetches feed bytes itself through this
transport - rather than handing a bare URL to `feedparser.parse()`,
which would perform its own internal fetch - so that the same
timeout/retry policy and fake-transport testability every other
PARIKA Tool already has (see `web_search`, `weather`, `currency`)
applies here too. `feedparser.parse()` is then given the already
fetched bytes to parse only (see `feed_reader.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .exceptions import NewsNetworkError, NewsTimeoutError

DEFAULT_USER_AGENT = "PARIKA-NewsTool/1.0"


@dataclass(frozen=True, slots=True, kw_only=True)
class HttpResponse:
    """
    Immutable, normalized HTTP response.
    """

    status_code: int
    url: str
    headers: Mapping[str, str]
    body: bytes


@runtime_checkable
class HttpTransport(Protocol):
    """
    Protocol implemented by every HTTP transport usable by the News
    Tool.
    """

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        """
        Perform an HTTP GET request.

        Raises:
            NewsTimeoutError:
                If the request exceeds `timeout`.

            NewsNetworkError:
                If the request fails for any other network reason.
        """
        ...


class UrllibHttpTransport:
    """
    Default HttpTransport implementation using the Python standard
    library's `urllib`. No third-party HTTP client dependency is
    introduced.
    """

    def __init__(self, *, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self._user_agent = user_agent

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        request = Request(
            url,
            headers={"User-Agent": self._user_agent},
            method="GET",
        )

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
            raise NewsTimeoutError(
                f"Request to '{url}' timed out after {timeout} seconds."
            ) from ex

        except URLError as ex:
            if isinstance(ex.reason, TimeoutError):
                raise NewsTimeoutError(
                    f"Request to '{url}' timed out after "
                    f"{timeout} seconds."
                ) from ex

            raise NewsNetworkError(
                f"Request to '{url}' failed: {ex.reason}"
            ) from ex

        return HttpResponse(
            status_code=status_code,
            url=final_url,
            headers=headers,
            body=body,
        )
