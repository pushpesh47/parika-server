"""
PARIKA Web Search Tool - Search Result

Defines the immutable SearchResult produced by a SearchBackend.
"""

from __future__ import annotations

from dataclasses import dataclass

from .page_content import PageContent


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class SearchResult:
    """
    Immutable single search result.
    """

    title: str
    """
    Result title as reported by the search backend.
    """

    url: str
    """
    Result URL - the actual destination, never a search provider's
    own redirect/tracking wrapper (e.g. `bing.com/ck/a?...`). Backends
    decode any such redirect whenever possible before populating this
    field; see each `search_backend_<provider>.py` for its own
    unwrapping logic.
    """

    snippet: str | None = None
    """
    Short excerpt describing the result, as reported by the search
    backend.
    """

    display_url: str | None = None
    """
    Human-readable, breadcrumb-style URL as the search provider
    displays it (e.g. `example.com > topic > page`), when the
    provider exposes one distinctly from the title and the real
    `url`. `None` when the provider does not expose one, or a backend
    has not been updated to populate it - existing code reading only
    `title`/`url`/`snippet` is entirely unaffected by this field's
    presence.
    """

    page: PageContent | None = None
    """
    Fetched and extracted page content for this result.

    Populated only when the caller requested page enrichment.
    """
