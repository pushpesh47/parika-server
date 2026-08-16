"""
PARIKA Web Search Tool - Result Ranking

Scores and reorders a SearchBackend's already-parsed results by their
relevance to the query, independent of whatever order the backend
itself reported them in.

Deliberately generic and provider-agnostic: this module has no
knowledge of Google, Bing, or any other specific backend, and no
knowledge of the query's topic or domain - it operates purely on
term overlap between the query and each result's title/snippet, which
works identically for a news query, a product search, or a technical
lookup (see `WebSearchToolDriver`'s module docstring: PARIKA is a
generic AI Kernel, not a news application).

Kept as its own module - not folded into `driver.py` or any
`search_backend_<provider>.py` - so "Ranking" remains a clean,
independently testable architectural layer distinct from "Provider"
(network I/O), "Parser" (HTML/JSON extraction), and "Result Selection"
(final truncation to the caller's requested count, `driver.py`'s own
responsibility once results are ranked).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .search_result import SearchResult

_TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "of", "in", "on", "at", "to", "for", "and",
        "or", "is", "are", "was", "were", "be", "been", "being", "it",
        "this", "that", "with", "as", "by", "from", "about",
    }
)
"""
A small, generic set of English function words excluded from term
overlap scoring so they never dominate relevance purely by frequency.
Deliberately limited to basic language mechanics (articles,
prepositions, common verbs) - never a topic- or domain-specific term -
so this remains a generic heuristic, not a hardcoded content rule.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class RankingWeights:
    """
    Tunable weights controlling how `rank_results()` scores a result.

    See `config.py`'s `WebSearchProviderConfig` for how these are
    read from `[web_search]` configuration rather than hardcoded.
    """

    title_weight: float = 2.0
    """How strongly query/title term overlap contributes to a result's score."""

    snippet_weight: float = 1.0
    """How strongly query/snippet term overlap contributes to a result's score."""

    position_decay: float = 0.01
    """
    Small per-position penalty applied to a backend's own reported
    order, so two results with identical term-overlap scores keep the
    backend's original relative order (its own relevance signal) as a
    tiebreaker, rather than an arbitrary one.
    """


DEFAULT_RANKING_WEIGHTS = RankingWeights()


def _tokenize(text: str | None) -> frozenset[str]:
    if not text:
        return frozenset()

    return frozenset(
        token
        for token in (match.group().lower() for match in _TOKEN_PATTERN.finditer(text))
        if token not in _STOPWORDS
    )


def _overlap_ratio(query_terms: frozenset[str], text_terms: frozenset[str]) -> float:
    if not query_terms or not text_terms:
        return 0.0

    return len(query_terms & text_terms) / len(query_terms)


def score_result(
    query_terms: frozenset[str],
    result: SearchResult,
    *,
    position: int,
    weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
) -> float:
    """
    Compute a single result's relevance score.

    Args:
        query_terms:
            Pre-tokenized query terms (see `_tokenize()`), computed
            once per `rank_results()` call rather than per result.

        result:
            The result to score.

        position:
            The result's index in the backend's own reported order
            (0 = first/most relevant per the backend itself).

        weights:
            Scoring weights.

    Returns:
        A relevance score; higher is more relevant. Only meaningful
        relative to other scores computed the same way - not a
        normalized probability or percentage.
    """

    title_overlap = _overlap_ratio(query_terms, _tokenize(result.title))
    snippet_overlap = _overlap_ratio(query_terms, _tokenize(result.snippet))

    return (
        title_overlap * weights.title_weight
        + snippet_overlap * weights.snippet_weight
        - position * weights.position_decay
    )


def rank_results(
    query: str,
    results: Sequence[SearchResult],
    *,
    weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
) -> tuple[SearchResult, ...]:
    """
    Score and reorder `results` by relevance to `query`, most
    relevant first.

    A stable sort is used, so results with an identical score (most
    commonly because neither the title nor the snippet shares any
    query term) keep the backend's own relative order rather than
    being shuffled arbitrarily.

    Args:
        query:
            The search query text the results should be scored
            against.

        results:
            Results to rank, in the backend's own reported order.

        weights:
            Scoring weights (see `RankingWeights`).

    Returns:
        `results`, reordered by descending relevance score. Always
        the same length as `results` - ranking only reorders, callers
        remain responsible for any final truncation ("Result
        Selection", `driver.py`'s own responsibility).
    """

    if not results:
        return ()

    query_terms = _tokenize(query)

    scored = sorted(
        enumerate(results),
        key=lambda pair: score_result(
            query_terms, pair[1], position=pair[0], weights=weights
        ),
        reverse=True,
    )

    return tuple(result for _, result in scored)
