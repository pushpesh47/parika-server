"""
PARIKA Web Search Tool - Result Deduplication

Removes exact-URL duplicates and same-domain near-duplicate results
from a candidate pool, using only the standard library
(`urllib.parse` for URL normalization, `difflib` for near-duplicate
title detection) - no new dependency, matching this Tool's existing
stdlib-only convention.

This addresses a gap identified during architecture verification
(Phase 1): the pipeline previously ranked and truncated a candidate
pool without ever removing duplicates, so a backend reporting the
same URL twice - or two backends (under `FailoverSearchBackend`,
future multi-backend merging) reporting the same page with tracking
parameters that differ only cosmetically - could both survive into
the final results.

Kept as its own module - not folded into `ranking.py` or `driver.py`
- so "Deduplication" remains its own clean, independently testable
pipeline stage, run once per search between "Provider" (raw fetch)
and "Ranking" (relevance scoring), exactly like `ranking.py` is its
own stage between "Provider" and "Result Selection" (see
`driver.py`'s own docstring for the full pipeline description).

At the result-set sizes this Tool operates at (`candidate_pool_size`,
default 20), the pairwise comparison this module performs is trivial
- there is no need for a specialized fuzzy-matching dependency (e.g.
`rapidfuzz`) purely to solve this at this scale; see
`docs/architecture/Tools_Expansion_Phase1_Plan.md` section 3.5 for
the full comparison.
"""

from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .search_result import SearchResult

DEFAULT_TITLE_SIMILARITY_THRESHOLD = 0.92
"""
Minimum `difflib.SequenceMatcher` ratio between two lowercased,
stripped titles for them to be considered a near-duplicate. Only
ever compared between results already sharing the same normalized
domain, so two unrelated sites with a generic, coincidentally similar
title (e.g. two different "Home" pages) are never merged.
"""

_TRACKING_PARAM_PREFIXES = (
    "utm_",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
)
"""
Common cross-site tracking query parameters stripped before URL
comparison, so `https://example.com/a?utm_source=x` and
`https://example.com/a` are recognized as the same page.
"""


def _is_tracking_param(name: str) -> bool:
    lowered = name.lower()

    return any(
        lowered == prefix or lowered.startswith(prefix)
        for prefix in _TRACKING_PARAM_PREFIXES
    )


def normalize_url(url: str) -> str:
    """
    Normalize a URL for duplicate comparison: lowercases the host,
    strips a leading `www.`, strips a trailing slash from the path,
    removes tracking query parameters, and sorts the remaining query
    parameters - all without changing which real page the URL
    identifies.
    """

    parts = urlsplit(url)

    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parts.path.rstrip("/") or "/"

    query_pairs = sorted(
        pair
        for pair in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(pair[0])
    )

    return urlunsplit(("https", netloc, path, urlencode(query_pairs), ""))


def _domain_of(url: str) -> str:
    netloc = urlsplit(url).netloc.lower()

    return netloc[4:] if netloc.startswith("www.") else netloc


def _titles_are_near_duplicates(
    first: str | None,
    second: str | None,
    *,
    threshold: float,
) -> bool:
    if not first or not second:
        return False

    ratio = SequenceMatcher(
        None, first.strip().lower(), second.strip().lower()
    ).ratio()

    return ratio >= threshold


def deduplicate_results(
    results: Sequence[SearchResult],
    *,
    title_similarity_threshold: float = DEFAULT_TITLE_SIMILARITY_THRESHOLD,
) -> tuple[SearchResult, ...]:
    """
    Remove exact-URL duplicates and same-domain near-duplicate
    results from a candidate pool, keeping the first (highest
    priority) occurrence of each.

    Args:
        results:
            Candidate results, in the backend's own reported order.

        title_similarity_threshold:
            Minimum title similarity ratio (see
            `DEFAULT_TITLE_SIMILARITY_THRESHOLD`) for two same-domain
            results to be treated as duplicates.

    Returns:
        `results` with duplicates removed, preserving the original
        relative order of every kept result. Never longer than
        `results`; ranking and truncation remain later pipeline
        stages' own responsibility.
    """

    if not results:
        return ()

    seen_urls: set[str] = set()
    kept: list[SearchResult] = []

    for result in results:
        normalized = normalize_url(result.url)

        if normalized in seen_urls:
            continue

        domain = _domain_of(result.url)

        if any(
            _domain_of(existing.url) == domain
            and _titles_are_near_duplicates(
                existing.title,
                result.title,
                threshold=title_similarity_threshold,
            )
            for existing in kept
        ):
            continue

        seen_urls.add(normalized)
        kept.append(result)

    return tuple(kept)
