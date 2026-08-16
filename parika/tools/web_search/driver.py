"""
PARIKA Web Search Tool - Driver

Implements the ToolDriver contract for the `web.search` capability.

WebSearchToolDriver coordinates a SearchBackend and a PageFetcher to
search the web and, optionally, enrich each result with fetched and
extracted page content. It contains no registration, lifecycle, or
capability-routing logic; that is owned by ToolManager, ModuleManager,
and the Web Search Module driver.

PARIKA is a generic AI Kernel, not a news, weather, or search
application: this driver, `ranking.py`, and every
`search_backend_<provider>.py` are all deliberately topic- and
domain-agnostic, and must remain so - none of them ever special-case
news wording or any other subject matter. The same pipeline serves a
technology query, a sports score, a product lookup, or a historical
question identically.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse

from .cache import SearchResultCache, make_cache_key
from .config import DEFAULT_CANDIDATE_POOL_SIZE, DEFAULT_MAX_RESULTS
from .dedup import DEFAULT_TITLE_SIMILARITY_THRESHOLD, deduplicate_results
from .exceptions import InvalidSearchQueryError, WebSearchToolError
from .page_content import PageContent
from .page_fetcher import PageFetcher
from .protocol import SearchBackend
from .query_normalizer import QueryNormalizer
from .ranking import DEFAULT_RANKING_WEIGHTS, RankingWeights, rank_results
from .search_result import SearchResult
from .validation import (
    DEFAULT_VALIDATION_CONFIG,
    SearchResultValidator,
    SearchValidationConfig,
)

_logger = logging.getLogger(__name__)


class WebSearchToolDriver:
    """
    ToolDriver implementing the `web.search` capability.

    Given a search query, this driver returns matching results and,
    when requested, fetches and extracts the readable content of each
    result page.

    Result handling is a clean pipeline, each stage independently
    swappable/testable:

    0. **Query Normalization** (`query_normalizer.QueryNormalizer`)
       rewrites a small set of recognized ambiguous or search-
       unfriendly phrasings (e.g. "current <role>" -> "incumbent
       <role>") before the query ever reaches a Provider, so a
       term-overlap-driven backend or ranker is never confused by an
       ambiguity a human reader would resolve instantly.
    1. **Provider** (`self._search_backend`) fetches and parses a
       *candidate pool* of raw results - deliberately larger than
       what the caller actually asked for (`candidate_pool_size`),
       so a relevant result reported near the end of a provider's
       own order is never discarded before ranking ever sees it (see
       Issue 6/7).
    2. **Deduplication** (`dedup.deduplicate_results()`) removes
       exact-URL and same-domain near-duplicate results from that
       pool, so a repeated result never occupies a slot ranking or
       truncation would otherwise have given to a distinct one.
    3. **Ranking** (`ranking.rank_results()`) scores and reorders the
       deduplicated pool by relevance to the query - generic,
       provider-agnostic, and topic-agnostic (see `ranking.py`'s own
       docstring).
    4. **Validation** (`validation.SearchResultValidator`) computes a
       heuristic confidence score for the ranked pool and, when it
       falls below a configured minimum, retries once with a
       further-rewritten query (see `query_normalizer.py`) rather
       than silently returning results a human would recognize as
       unrelated. A search is no longer considered successful merely
       because the HTTP request and parser succeeded.
    5. **Result Selection** (this method's own final slice) truncates
       the ranked pool down to the caller's actually requested count.
    """

    def __init__(
        self,
        *,
        search_backend: SearchBackend,
        page_fetcher: PageFetcher,
        default_max_results: int = DEFAULT_MAX_RESULTS,
        candidate_pool_size: int = DEFAULT_CANDIDATE_POOL_SIZE,
        ranking_enabled: bool = True,
        ranking_weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
        dedup_enabled: bool = True,
        dedup_title_similarity_threshold: float = (
            DEFAULT_TITLE_SIMILARITY_THRESHOLD
        ),
        validation_enabled: bool = True,
        validation_config: SearchValidationConfig = DEFAULT_VALIDATION_CONFIG,
        query_normalizer: QueryNormalizer | None = None,
        cache: SearchResultCache | None = None,
    ) -> None:
        """
        Initialize the driver.

        Args:
            search_backend:
                Backend used to perform the search itself.

            page_fetcher:
                Fetcher used to enrich results with page content when
                requested.

            default_max_results:
                Default maximum number of results returned when a
                caller does not specify `max_results` itself. See
                `config.WebSearchProviderConfig.default_max_results`.

            candidate_pool_size:
                How many results to request from `search_backend`
                before ranking and truncating to the actually
                requested count; always raised to at least that
                count. See
                `config.WebSearchProviderConfig.candidate_pool_size`.

            ranking_enabled:
                Whether to rank the candidate pool by relevance to
                the query (see `ranking.py`) before truncating, rather
                than trusting the backend's own raw order verbatim.

            ranking_weights:
                Weights used when ranking is enabled. See
                `ranking.RankingWeights`.

            dedup_enabled:
                Whether to remove exact-URL and same-domain
                near-duplicate results from the candidate pool before
                ranking. See `dedup.py`.

            dedup_title_similarity_threshold:
                Similarity threshold used when `dedup_enabled` is
                true. See `dedup.DEFAULT_TITLE_SIMILARITY_THRESHOLD`.

            validation_enabled:
                Whether to normalize the query (see
                `query_normalizer.py`) and validate the ranked
                candidate pool's heuristic confidence (see
                `validation.py`) before truncating, retrying once
                with a rewritten query when confidence is low. A
                full kill switch requiring no code change, following
                the same convention as `ranking_enabled`/
                `dedup_enabled`.

            validation_config:
                Weights/thresholds used when `validation_enabled` is
                true. See `validation.SearchValidationConfig`.

            query_normalizer:
                Optional `QueryNormalizer` override, primarily for
                tests. Defaults to a fresh, stateless
                `QueryNormalizer()`.

            cache:
                Optional `SearchResultCache`. When supplied, the
                ranked (pre-page-fetch) candidate pool for a given
                normalized query is cached and reused within its TTL
                (see `cache.py`) instead of re-querying the backend.
                Defaults to `None` (no caching), so every existing
                caller/test that does not pass this argument is
                unaffected.
        """

        self._search_backend = search_backend
        self._page_fetcher = page_fetcher
        self._default_max_results = default_max_results
        self._candidate_pool_size = candidate_pool_size
        self._ranking_enabled = ranking_enabled
        self._ranking_weights = ranking_weights
        self._dedup_enabled = dedup_enabled
        self._dedup_title_similarity_threshold = dedup_title_similarity_threshold
        self._validation_enabled = validation_enabled
        self._search_validator = SearchResultValidator(validation_config)
        self._query_normalizer = query_normalizer or QueryNormalizer()
        self._cache = cache

    def execute(self, request: ToolRequest) -> ToolResponse:
        """
        Execute a web search.

        Expected `request.arguments`:
            query (str):
                Required search query text.

            max_results (int):
                Optional maximum number of results. Defaults to
                `default_max_results`.

            include_content (bool):
                Optional flag requesting that each result's page be
                fetched and its content extracted. Defaults to False.
                Page fetch failures for individual results are
                tolerated on a best-effort basis and do not fail the
                overall search.

        Returns:
            ToolResponse whose `result` is a tuple of plain dicts
            (one per SearchResult) and whose `attributes` report the
            executed query and the number of results returned. When
            `validation_enabled` is true, `attributes["validation"]`
            additionally reports `confidence` (float), `retried`
            (bool), `rewritten_query` (str or None), and
            `low_confidence` (bool) - see `_validate_candidates()`.
            A low-confidence result set is still returned (never
            raised as an error): this is a graceful degradation, not
            a failure, so callers/models can decide how to present
            it rather than receiving nothing at all.

        Raises:
            InvalidSearchQueryError:
                If `query` is missing, empty, or not a string.

            WebSearchTimeoutError:
                If the search request times out on every attempt.

            WebSearchNetworkError:
                If the search request fails on every attempt for
                another network reason.
        """

        query = request.arguments.get("query")

        if not isinstance(query, str) or not query.strip():
            raise InvalidSearchQueryError(
                "request.arguments['query'] must be a non-empty "
                "string."
            )

        raw_max_results: Any = request.arguments.get(
            "max_results", self._default_max_results
        )
        max_results = int(raw_max_results)

        include_content = bool(
            request.arguments.get("include_content", False)
        )

        candidate_pool_size = max(max_results, self._candidate_pool_size)

        effective_query = (
            self._query_normalizer.normalize(query)
            if self._validation_enabled
            else query
        )

        candidates = self._run_search_pipeline(
            effective_query, candidate_pool_size
        )

        validation_attributes: dict[str, Any] | None = None

        if self._validation_enabled:
            candidates, effective_query, validation_attributes = (
                self._validate_candidates(
                    original_query=query,
                    effective_query=effective_query,
                    candidates=candidates,
                    candidate_pool_size=candidate_pool_size,
                )
            )

        results = candidates[:max_results]

        _logger.debug(
            "Web search result selection: query=%r effective_query=%r "
            "selected=%d (max_results=%d, candidate_pool_size=%d)",
            query,
            effective_query,
            len(results),
            max_results,
            candidate_pool_size,
        )

        if include_content:
            results = tuple(
                self._enrich_with_page_content(result)
                for result in results
            )

        attributes: dict[str, Any] = {
            "query": query,
            "result_count": len(results),
        }

        if validation_attributes is not None:
            attributes["validation"] = validation_attributes

        return ToolResponse(
            result=tuple(_result_to_dict(result) for result in results),
            attributes=attributes,
        )

    def _run_search_pipeline(
        self,
        query: str,
        candidate_pool_size: int,
    ) -> tuple[SearchResult, ...]:
        """
        Run the Provider -> Deduplication -> Ranking stages for
        `query`, returning the ranked (not yet truncated) candidate
        pool. Reuses a cached pool when `self._cache` is configured
        and a fresh (within-TTL) entry exists for this normalized
        query and backend.
        """

        cache_key = (
            make_cache_key(query, type(self._search_backend).__name__)
            if self._cache is not None
            else None
        )

        if cache_key is not None:
            cached = self._cache.get(cache_key)  # type: ignore[union-attr]

            if cached is not None:
                _logger.debug("Web search cache hit for query=%r.", query)
                return cached

        candidates = self._search_backend.search(
            query,
            max_results=candidate_pool_size,
        )

        candidate_count = len(candidates)

        if self._dedup_enabled:
            candidates = deduplicate_results(
                candidates,
                title_similarity_threshold=(
                    self._dedup_title_similarity_threshold
                ),
            )

        deduplicated_count = len(candidates)

        if self._ranking_enabled:
            candidates = rank_results(
                query, candidates, weights=self._ranking_weights
            )

        _logger.debug(
            "Web search pipeline: query=%r candidates=%d after_dedup=%d "
            "dedup_enabled=%s ranking_enabled=%s "
            "(candidate_pool_size=%d)",
            query,
            candidate_count,
            deduplicated_count,
            self._dedup_enabled,
            self._ranking_enabled,
            candidate_pool_size,
        )

        if cache_key is not None:
            self._cache.set(cache_key, candidates)  # type: ignore[union-attr]

        return candidates

    def _validate_candidates(
        self,
        *,
        original_query: str,
        effective_query: str,
        candidates: tuple[SearchResult, ...],
        candidate_pool_size: int,
    ) -> tuple[tuple[SearchResult, ...], str, dict[str, Any]]:
        """
        Gate `candidates` on heuristic confidence (see
        `validation.py`), retrying once with a further-rewritten
        query (see `query_normalizer.QueryNormalizer.
        rewrite_for_retry()`) when confidence is below the
        configured minimum. A retry is skipped whenever the
        rewritten query is identical to the query already attempted,
        since re-issuing an identical query to a deterministic
        backend cannot change the outcome.

        Args:
            original_query:
                The raw query exactly as supplied by the caller,
                before any normalization.

            effective_query:
                The (possibly normalized) query that produced
                `candidates`.

            candidates:
                The ranked (not yet truncated) candidate pool
                produced by `_run_search_pipeline(effective_query,
                ...)`.

            candidate_pool_size:
                Candidate pool size to use for any retry attempt.

        Returns:
            A `(candidates, effective_query, validation_attributes)`
            triple: the candidate pool and effective query from
            whichever attempt was ultimately used, plus a dict
            describing the validation outcome (always present - see
            `execute()`'s own docstring for its shape).
        """

        config = self._search_validator.config
        confidence = self._search_validator.best_confidence(
            effective_query, candidates
        )
        retried = False

        for _ in range(config.max_retries):
            if confidence >= config.min_confidence:
                break

            retry_query = self._query_normalizer.rewrite_for_retry(
                effective_query
            )

            if retry_query == effective_query:
                break

            _logger.debug(
                "Web search confidence %.3f below threshold %.3f for "
                "query=%r; retrying with rewritten query=%r.",
                confidence,
                config.min_confidence,
                effective_query,
                retry_query,
            )

            effective_query = retry_query
            candidates = self._run_search_pipeline(
                effective_query, candidate_pool_size
            )
            confidence = self._search_validator.best_confidence(
                effective_query, candidates
            )
            retried = True

        low_confidence = confidence < config.min_confidence

        if low_confidence:
            _logger.warning(
                "Web search returned low-confidence results "
                "(confidence=%.3f, threshold=%.3f) for query=%r after "
                "%s; returning results with low_confidence=True "
                "rather than failing outright.",
                confidence,
                config.min_confidence,
                original_query,
                "retry" if retried else "no retry",
            )

        rewritten_query = (
            effective_query if effective_query != original_query else None
        )

        return (
            candidates,
            effective_query,
            {
                "confidence": confidence,
                "retried": retried,
                "rewritten_query": rewritten_query,
                "low_confidence": low_confidence,
            },
        )

    def _enrich_with_page_content(
        self,
        result: SearchResult,
    ) -> SearchResult:
        """
        Attempt to fetch and attach page content for a single result.

        Failures are tolerated on a best-effort basis: the original
        result is returned unchanged if the page cannot be fetched.
        """

        try:
            page = self._page_fetcher.fetch(result.url)

        except WebSearchToolError:
            return result

        return replace(result, page=page)


def _result_to_dict(result: SearchResult) -> dict[str, Any]:
    """
    Convert a SearchResult into a plain, JSON-serializable dict.
    """

    payload: dict[str, Any] = {
        "title": result.title,
        "url": result.url,
        "snippet": result.snippet,
        "display_url": result.display_url,
    }

    if result.page is not None:
        payload["page"] = _page_to_dict(result.page)

    return payload


def _page_to_dict(page: PageContent) -> dict[str, Any]:
    """
    Convert a PageContent into a plain, JSON-serializable dict.
    """

    return {
        "url": page.url,
        "final_url": page.final_url,
        "status_code": page.status_code,
        "title": page.title,
        "description": page.description,
        "text": page.text,
        "content_type": page.content_type,
        "content_length": page.content_length,
        "fetched_at": page.fetched_at.isoformat(),
    }
