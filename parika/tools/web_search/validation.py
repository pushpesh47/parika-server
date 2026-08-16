"""
PARIKA Web Search Tool - Result Validation

Computes a heuristic confidence score for each search result relative
to the query, and gates whether a result set is confident enough to
return as-is versus warranting a retry with a rewritten query (Phase
1 Item 2: "Add Search Result Validation").

Previously, a search was considered successful whenever the HTTP
request and the parser succeeded, regardless of whether the returned
content actually related to the query. This module adds a heuristic
minimum-relevance gate on top of that: term overlap across each
result's title, snippet, and URL, weighted and combined into a single
[0, 1] confidence score per result.

Deliberately heuristic and stdlib-only (term overlap, not an
embedding/semantic model), consistent with `ranking.py`'s own
term-overlap approach and this Tool's stdlib-first convention: this
module performs "heuristic confidence scoring", never "semantic
relevance scoring" - it has no notion of meaning, only of shared
terms between the query and a result's metadata.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

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
Mirrors `ranking.py`'s own stopword list: a small, generic set of
English function words excluded from term overlap scoring so they
never dominate a confidence score purely by frequency. Kept as its
own copy - rather than importing `ranking.py`'s private constant -
so this module has no dependency on `ranking.py`'s internals; both
lists independently address the exact same generic-term-overlap
concern.
"""

DEFAULT_VALIDATION_MIN_CONFIDENCE = 0.15
DEFAULT_VALIDATION_MAX_RETRIES = 1
DEFAULT_VALIDATION_TITLE_WEIGHT = 0.5
DEFAULT_VALIDATION_SNIPPET_WEIGHT = 0.3
DEFAULT_VALIDATION_URL_WEIGHT = 0.2


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchValidationConfig:
    """
    Tunable weights and thresholds controlling
    `SearchResultValidator`.

    Mirrors `ranking.RankingWeights`'s role: a small, dedicated
    configuration object assembled by the Web Search Module driver
    from `[web_search]` configuration (see `config.py`), rather than
    a parallel configuration system.
    """

    min_confidence: float = DEFAULT_VALIDATION_MIN_CONFIDENCE
    """
    Minimum heuristic confidence score, in [0, 1], at least one
    result must reach for the result set to be considered
    confidently relevant. Below this, `WebSearchToolDriver` retries
    once with a rewritten query (see `query_normalizer.py`) before
    falling back to a graceful, annotated low-confidence response.
    """

    max_retries: int = DEFAULT_VALIDATION_MAX_RETRIES
    """
    Maximum number of retry attempts with a rewritten query when
    confidence remains below `min_confidence`. A retry is separately
    skipped whenever the rewritten query is identical to the query
    already attempted (see `driver.py`), since re-issuing an
    identical query to a deterministic backend cannot change the
    outcome.
    """

    title_weight: float = DEFAULT_VALIDATION_TITLE_WEIGHT
    """How strongly query/title term overlap contributes to a result's confidence."""

    snippet_weight: float = DEFAULT_VALIDATION_SNIPPET_WEIGHT
    """How strongly query/snippet term overlap contributes to a result's confidence."""

    url_weight: float = DEFAULT_VALIDATION_URL_WEIGHT
    """How strongly query/URL term overlap contributes to a result's confidence."""


DEFAULT_VALIDATION_CONFIG = SearchValidationConfig()


def _tokenize(text: str | None) -> frozenset[str]:
    if not text:
        return frozenset()

    return frozenset(
        token
        for token in (
            match.group().lower() for match in _TOKEN_PATTERN.finditer(text)
        )
        if token not in _STOPWORDS
    )


def _url_tokens(url: str) -> frozenset[str]:
    """
    Tokenize the host and path portions of a URL - never the query
    string or fragment, which routinely carry tracking/session noise
    unrelated to the page's actual subject.
    """

    parts = urlsplit(url)
    text = f"{parts.netloc} {parts.path}".replace(".", " ").replace("/", " ").replace("-", " ")

    return _tokenize(text)


def _overlap_ratio(
    query_terms: frozenset[str],
    text_terms: frozenset[str],
) -> float:
    if not query_terms or not text_terms:
        return 0.0

    return len(query_terms & text_terms) / len(query_terms)


class SearchResultValidator:
    """
    Computes heuristic confidence scores for search results and
    gates whether a result set meets the configured minimum
    confidence.
    """

    def __init__(
        self,
        config: SearchValidationConfig = DEFAULT_VALIDATION_CONFIG,
    ) -> None:
        """
        Initialize the validator.

        Args:
            config:
                Tunable weights/thresholds. Defaults to
                `DEFAULT_VALIDATION_CONFIG`.
        """

        self._config = config

    @property
    def config(self) -> SearchValidationConfig:
        """The validation configuration this instance was built with."""

        return self._config

    def score_result(
        self,
        query_terms: frozenset[str],
        result: SearchResult,
    ) -> float:
        """
        Compute one result's heuristic confidence score.

        Args:
            query_terms:
                Pre-tokenized query terms (see `_tokenize()`),
                computed once per `score_results()` call rather than
                per result.

            result:
                The result to score.

        Returns:
            A confidence score in [0, 1]: the weighted average of
            title, snippet, and URL term-overlap ratios.
        """

        weights = self._config
        total_weight = (
            weights.title_weight + weights.snippet_weight + weights.url_weight
        )

        if total_weight <= 0:
            return 0.0

        title_overlap = _overlap_ratio(query_terms, _tokenize(result.title))
        snippet_overlap = _overlap_ratio(query_terms, _tokenize(result.snippet))
        url_overlap = _overlap_ratio(query_terms, _url_tokens(result.url))

        weighted_sum = (
            title_overlap * weights.title_weight
            + snippet_overlap * weights.snippet_weight
            + url_overlap * weights.url_weight
        )

        return weighted_sum / total_weight

    def score_results(
        self,
        query: str,
        results: Sequence[SearchResult],
    ) -> tuple[tuple[SearchResult, float], ...]:
        """
        Score every result against `query`.

        Args:
            query:
                Query text to score results against.

            results:
                Results to score, in any order.

        Returns:
            `(result, confidence)` pairs in the same order as
            `results`.
        """

        query_terms = _tokenize(query)

        return tuple(
            (result, self.score_result(query_terms, result))
            for result in results
        )

    def best_confidence(
        self,
        query: str,
        results: Sequence[SearchResult],
    ) -> float:
        """
        Return the highest confidence score among `results`, or
        `0.0` when `results` is empty.
        """

        if not results:
            return 0.0

        return max(
            confidence for _, confidence in self.score_results(query, results)
        )

    def is_confident(
        self,
        query: str,
        results: Sequence[SearchResult],
    ) -> bool:
        """
        Return True if at least one result meets
        `config.min_confidence`.
        """

        return self.best_confidence(query, results) >= self._config.min_confidence
