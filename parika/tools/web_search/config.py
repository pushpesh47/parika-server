"""
PARIKA Web Search Tool - Provider Configuration

Reads the `[web_search]` TOML section through the existing
`Configuration` Core component and exposes it as a small, typed,
read-only snapshot, following the same pattern as
`parika/core/planner/model_selection/config.py`.

This module is a thin wrapper, not a parallel configuration system:
`Configuration` remains the single source of truth for every value
here. `load_web_search_config()` performs nothing but
`Configuration.get()` calls, merged over built-in defaults, so search
provider selection behaves sensibly even when `[web_search]` (or all
of it) is absent - which is also why `WebSearchModuleDriver` continues
to default to a single working provider when constructed without a
`Configuration` at all (`None`), exactly preserving today's behavior
for every existing caller/test.

Only providers that require additional configuration get their own
sub-section - today, only `google_cse` (`[web_search.google_cse]`,
read here as `google_cse_api_key`/`google_cse_search_engine_id`).
Every other provider (`google`, `bing`, `duckduckgo`, `mojeek`,
`qwant`) needs no configuration of its own and is always considered
available; see `provider_registry.py`.

`WebSearchProviderConfig` covers every tunable value in the
`[web_search]` section - not only provider selection but also result
selection/ranking (`candidate_pool_size`, `default_max_results`,
`ranking_enabled`, `ranking_*_weight`; see `ranking.py`). These remain
one config section/dataclass because they are one small, cohesive set
of operator-facing settings; the *runtime* separation the settings
configure - Provider, Parser, Ranking, and Result Selection each
staying independent, swappable components - is enforced by
`provider_registry.py`, each `search_backend_<provider>.py`,
`ranking.py`, and `driver.py` respectively, not by how configuration
happens to be grouped.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

DEFAULT_MAX_RESULTS = 10
"""
Default maximum results `WebSearchToolDriver` returns when a caller
does not specify `max_results` itself. Previously a driver-local
constant fixed at 5, which is exactly what discarded a relevant
result appearing at rank 10 (Issue 6) - doubled here, and now
config-driven (`[web_search].default_max_results`) rather than
hardcoded, so operators can tune it without a code change.
"""

DEFAULT_CANDIDATE_POOL_SIZE = 20
"""
Default number of results requested from the configured
`SearchBackend` before ranking and truncating to the actually
requested count (see `WebSearchProviderConfig.candidate_pool_size`
and `ranking.py`). Comfortably larger than `DEFAULT_MAX_RESULTS` so a
highly relevant result near the end of a typical single-page result
set is never discarded before ranking ever sees it.
"""

DEFAULT_PROVIDER = "google"
"""
Google is the default provider: it consistently produces the
highest-quality, most broadly relevant results of every no-API-key
provider PARIKA implements. DuckDuckGo - the previous default - is
deliberately no longer the default because it frequently encounters
anti-bot protection (see `search_backend_duckduckgo.py`), even though
it remains a configured failover option.
"""

DEFAULT_VALIDATION_MIN_CONFIDENCE = 0.15
"""
Default minimum heuristic confidence score (see `validation.py`'s
`SearchResultValidator`) at least one result must reach for a search
to be considered confidently relevant, before
`WebSearchToolDriver.execute()` retries once with a rewritten query.
"""

DEFAULT_VALIDATION_MAX_RETRIES = 1
"""
Default maximum number of retry attempts with a rewritten query when
confidence remains below `DEFAULT_VALIDATION_MIN_CONFIDENCE`. A
retry is additionally skipped whenever the rewritten query is
identical to the query already attempted, since re-issuing an
identical query to a deterministic backend cannot change the
outcome.
"""

DEFAULT_VALIDATION_TITLE_WEIGHT = 0.5
DEFAULT_VALIDATION_SNIPPET_WEIGHT = 0.3
DEFAULT_VALIDATION_URL_WEIGHT = 0.2

DEFAULT_PROVIDER_ORDER: tuple[str, ...] = (DEFAULT_PROVIDER,)
"""
Fallback provider order used only when `configuration` is `None`
entirely, or `[web_search].provider_order` is missing from whatever
was supplied - deliberately a single provider, exactly the same
"no Configuration -> today's simple, single-provider behavior"
convention `WebSearchProviderConfig`'s other fields already follow
(and the same convention `model_selection/config.py` follows), so
every existing caller/test that never supplies a `Configuration`
still gets exactly one HTTP request per search, unaffected by this
Tool now supporting several providers.

The full, multi-provider failover order - `google`, `bing`,
`duckduckgo`, `mojeek`, `qwant`, `google_cse`, ordered for AI-quality
search results rather than popularity - lives in
`config/defaults.toml`'s `[web_search].provider_order`, which is what
every real, production `Configuration` (loaded via
`Configuration.load()`, as `build_default_runtime()` always does)
actually resolves to. This constant is never consulted once that key
is present, at any configuration layer.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class WebSearchProviderConfig:
    """
    Immutable, typed snapshot of `[web_search]` configuration.
    """

    enabled: bool = True
    """
    Whether the Web Search Module should be active at all. Mirrors
    the same `enabled` convention as `[providers.ollama].enabled`.
    """

    default_provider: str = DEFAULT_PROVIDER
    """
    Name of the search provider to try first. Must be one of the
    names registered in `provider_registry.PROVIDER_REGISTRY` for the
    default backend to actually resolve to it; an unrecognized name
    is simply skipped (see `provider_registry.build_search_backend()`).
    """

    provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER
    """
    Every provider name configured for this installation, in the
    order failover should attempt them after `default_provider`.
    `default_provider` need not be repeated in this list.
    """

    google_cse_api_key: str = ""
    """
    API key for Google Custom Search (`[web_search.google_cse]`).
    When empty, `provider_registry.py` treats `google_cse` as
    unavailable and skips it entirely.
    """

    google_cse_search_engine_id: str = ""
    """
    Search Engine ID (`cx`) for Google Custom Search
    (`[web_search.google_cse]`). When empty,
    `provider_registry.py` treats `google_cse` as unavailable and
    skips it entirely.
    """

    default_max_results: int = DEFAULT_MAX_RESULTS
    """
    Default maximum number of results `WebSearchToolDriver` returns
    when a caller (typically the model, via its tool call arguments)
    does not specify `max_results` itself.
    """

    candidate_pool_size: int = DEFAULT_CANDIDATE_POOL_SIZE
    """
    How many results `WebSearchToolDriver` requests from the
    configured `SearchBackend` before ranking and truncating to the
    caller's actual requested count - always at least as large as
    that requested count. A pool larger than the final requested
    count is what allows ranking to promote a highly relevant result
    that a backend happened to report near the end of its own order
    (see `ranking.py` and Issue 6/7's own reasoning) instead of it
    being discarded by truncation before ranking ever sees it.
    """

    ranking_enabled: bool = True
    """
    Whether `WebSearchToolDriver` ranks candidate results by
    relevance to the query (`ranking.py`) before truncating to the
    requested count, rather than trusting the backend's own raw
    order verbatim. A full kill switch requiring no code change.
    """

    ranking_title_weight: float = 2.0
    """See `ranking.RankingWeights.title_weight`."""

    ranking_snippet_weight: float = 1.0
    """See `ranking.RankingWeights.snippet_weight`."""

    ranking_position_decay: float = 0.01
    """See `ranking.RankingWeights.position_decay`."""

    dedup_enabled: bool = True
    """
    Whether `WebSearchToolDriver` removes exact-URL and same-domain
    near-duplicate results from the candidate pool before ranking
    (see `dedup.py`). A full kill switch requiring no code change.
    """

    dedup_title_similarity_threshold: float = 0.92
    """See `dedup.DEFAULT_TITLE_SIMILARITY_THRESHOLD`."""

    validation_enabled: bool = True
    """
    Whether `WebSearchToolDriver` validates result relevance (see
    `validation.py`) and retries once with a rewritten query when
    confidence is low, rather than trusting any HTTP-successful,
    parser-successful response as relevant. A full kill switch
    requiring no code change, following the same convention as
    `ranking_enabled`/`dedup_enabled`.
    """

    validation_min_confidence: float = DEFAULT_VALIDATION_MIN_CONFIDENCE
    """See `validation.SearchValidationConfig.min_confidence`."""

    validation_max_retries: int = DEFAULT_VALIDATION_MAX_RETRIES
    """See `validation.SearchValidationConfig.max_retries`."""

    validation_title_weight: float = DEFAULT_VALIDATION_TITLE_WEIGHT
    """See `validation.SearchValidationConfig.title_weight`."""

    validation_snippet_weight: float = DEFAULT_VALIDATION_SNIPPET_WEIGHT
    """See `validation.SearchValidationConfig.snippet_weight`."""

    validation_url_weight: float = DEFAULT_VALIDATION_URL_WEIGHT
    """See `validation.SearchValidationConfig.url_weight`."""

    cache_enabled: bool = True
    """
    Whether `WebSearchToolDriver` caches the ranked (pre-page-fetch)
    candidate pool per normalized query, keyed by backend identity
    (see `cache.py`). A full kill switch requiring no code change,
    following the same convention as `ranking_enabled`/`dedup_enabled`.
    """

    cache_ttl_seconds: float = 900.0
    """How long a cached candidate pool remains valid. See `cache.py`."""

    cache_max_entries: int = 500
    """Maximum number of cache entries retained. See `cache.py`."""

    def failover_order(self) -> tuple[str, ...]:
        """
        Return every configured provider name, `default_provider`
        first, then every other configured provider in the order
        given by `provider_order`, with duplicates removed.
        """

        ordered: list[str] = []

        for name in (self.default_provider, *self.provider_order):
            if name not in ordered:
                ordered.append(name)

        return tuple(ordered)


def load_web_search_config(
    configuration: Configuration | None,
) -> WebSearchProviderConfig:
    """
    Build a `WebSearchProviderConfig` snapshot from `Configuration`.

    Args:
        configuration:
            The Core `Configuration` component. When `None`, every
            value falls back to its built-in default, so the Web
            Search Module remains fully functional (matching today's
            behavior) without requiring every caller to supply a
            Configuration.

    Returns:
        The resolved, immutable configuration snapshot.
    """

    if configuration is None:
        return WebSearchProviderConfig()

    provider_order_raw = configuration.get(
        "web_search.provider_order", list(DEFAULT_PROVIDER_ORDER)
    )

    if isinstance(provider_order_raw, (list, tuple)):
        provider_order = tuple(str(name) for name in provider_order_raw)
    else:
        provider_order = DEFAULT_PROVIDER_ORDER

    default_provider = str(
        configuration.get(
            "web_search.default_provider",
            provider_order[0] if provider_order else DEFAULT_PROVIDER,
        )
    )

    default_max_results = int(
        configuration.get(
            "web_search.default_max_results", DEFAULT_MAX_RESULTS
        )
    )
    candidate_pool_size = int(
        configuration.get(
            "web_search.candidate_pool_size", DEFAULT_CANDIDATE_POOL_SIZE
        )
    )

    return WebSearchProviderConfig(
        enabled=bool(configuration.get("web_search.enabled", True)),
        default_provider=default_provider,
        provider_order=provider_order,
        google_cse_api_key=str(
            configuration.get("web_search.google_cse.api_key", "")
        ),
        google_cse_search_engine_id=str(
            configuration.get(
                "web_search.google_cse.search_engine_id", ""
            )
        ),
        default_max_results=default_max_results,
        candidate_pool_size=max(candidate_pool_size, default_max_results),
        ranking_enabled=bool(
            configuration.get("web_search.ranking_enabled", True)
        ),
        ranking_title_weight=float(
            configuration.get("web_search.ranking_title_weight", 2.0)
        ),
        ranking_snippet_weight=float(
            configuration.get("web_search.ranking_snippet_weight", 1.0)
        ),
        ranking_position_decay=float(
            configuration.get("web_search.ranking_position_decay", 0.01)
        ),
        dedup_enabled=bool(
            configuration.get("web_search.dedup_enabled", True)
        ),
        dedup_title_similarity_threshold=float(
            configuration.get(
                "web_search.dedup_title_similarity_threshold", 0.92
            )
        ),
        validation_enabled=bool(
            configuration.get("web_search.validation_enabled", True)
        ),
        validation_min_confidence=float(
            configuration.get(
                "web_search.validation_min_confidence",
                DEFAULT_VALIDATION_MIN_CONFIDENCE,
            )
        ),
        validation_max_retries=int(
            configuration.get(
                "web_search.validation_max_retries",
                DEFAULT_VALIDATION_MAX_RETRIES,
            )
        ),
        validation_title_weight=float(
            configuration.get(
                "web_search.validation_title_weight",
                DEFAULT_VALIDATION_TITLE_WEIGHT,
            )
        ),
        validation_snippet_weight=float(
            configuration.get(
                "web_search.validation_snippet_weight",
                DEFAULT_VALIDATION_SNIPPET_WEIGHT,
            )
        ),
        validation_url_weight=float(
            configuration.get(
                "web_search.validation_url_weight",
                DEFAULT_VALIDATION_URL_WEIGHT,
            )
        ),
        cache_enabled=bool(
            configuration.get("web_search.cache_enabled", True)
        ),
        cache_ttl_seconds=float(
            configuration.get("web_search.cache_ttl_seconds", 900.0)
        ),
        cache_max_entries=int(
            configuration.get("web_search.cache_max_entries", 500)
        ),
    )
