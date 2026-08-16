"""
PARIKA News Tool - News Item

Defines the immutable NewsItem produced by parsing one feed entry.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class NewsItem:
    """
    Immutable single news article, normalized from one feed entry
    regardless of whether the underlying feed was RSS, Atom, or RDF -
    `feedparser` itself absorbs that format difference (see
    `feed_reader.py`).
    """

    title: str
    link: str
    summary: str | None
    source: str | None
    published: str | None
    """Raw, provider-reported publication date/time string, if any."""

    published_at: str | None
    """
    ISO 8601 UTC timestamp derived from the feed entry's parsed
    publication time, when the feed supplied one PARIKA could parse.
    `None` when the feed did not supply a parseable date - callers
    should not assume every item has one.
    """
