"""
PARIKA Web Search Tool - Page Content

Defines the immutable PageContent produced by fetching and extracting
a single web page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class PageContent:
    """
    Immutable result of fetching and extracting a single web page.
    """

    url: str
    """
    URL that was requested.
    """

    final_url: str
    """
    URL actually served, after following redirects.
    """

    status_code: int
    """
    HTTP status code returned for the request.
    """

    title: str | None
    """
    Extracted page title, if present.
    """

    description: str | None
    """
    Extracted meta description, if present.
    """

    text: str
    """
    Extracted, whitespace-normalized visible text content.
    """

    content_type: str | None
    """
    Reported `Content-Type` response header, if present.
    """

    content_length: int
    """
    Size, in bytes, of the raw response body.
    """

    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(UTC),
    )
    """
    Timestamp when the page was fetched.
    """
