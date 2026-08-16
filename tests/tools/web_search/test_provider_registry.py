"""
Unit tests for `parika.tools.web_search.provider_registry`.
"""

from __future__ import annotations

import pytest

from parika.tools.web_search.config import WebSearchProviderConfig
from parika.tools.web_search.exceptions import WebSearchTimeoutError
from parika.tools.web_search.provider_registry import (
    PROVIDER_REGISTRY,
    BackendTuning,
    ProviderRegistration,
    build_search_backend,
)
from parika.tools.web_search.search_backend_bing import BingHtmlSearchBackend
from parika.tools.web_search.search_backend_duckduckgo import (
    DuckDuckGoHtmlSearchBackend,
)
from parika.tools.web_search.search_backend_failover import (
    FailoverSearchBackend,
)
from parika.tools.web_search.search_backend_google import (
    GoogleHtmlSearchBackend,
)
from parika.tools.web_search.search_backend_google_cse import (
    GoogleCseSearchBackend,
)
from parika.tools.web_search.search_backend_mojeek import (
    MojeekHtmlSearchBackend,
)
from parika.tools.web_search.search_backend_parallel_mcp import (
    ParallelMcpSearchBackend,
)
from parika.tools.web_search.search_backend_qwant import (
    QwantHtmlSearchBackend,
)
from parika.tools.web_search.search_result import SearchResult


class _FakeBackend:
    def __init__(
        self,
        *,
        result: tuple[SearchResult, ...] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(
        self, query: str, *, max_results: int
    ) -> tuple[SearchResult, ...]:
        self.calls.append((query, max_results))

        if self.error is not None:
            raise self.error

        assert self.result is not None
        return self.result


SUCCESS_RESULT = (SearchResult(title="PARIKA", url="https://example.com"),)


class TestProviderRegistryContents:
    """
    Every provider named in `config.DEFAULT_PROVIDER_ORDER` must
    actually be registered, and every no-configuration provider must
    default to always-available.
    """

    def test_every_provider_is_registered(self) -> None:
        expected = {
            "google",
            "bing",
            "duckduckgo",
            "mojeek",
            "qwant",
            "parallel_mcp",
            "google_cse",
        }

        assert set(PROVIDER_REGISTRY) == expected

    @pytest.mark.parametrize(
        ("name", "expected_type"),
        [
            ("google", GoogleHtmlSearchBackend),
            ("bing", BingHtmlSearchBackend),
            ("duckduckgo", DuckDuckGoHtmlSearchBackend),
            ("mojeek", MojeekHtmlSearchBackend),
            ("qwant", QwantHtmlSearchBackend),
            ("parallel_mcp", ParallelMcpSearchBackend),
        ],
    )
    def test_no_configuration_provider_builds_expected_backend_type(
        self, name: str, expected_type: type
    ) -> None:
        registration = PROVIDER_REGISTRY[name]

        assert registration.is_available(WebSearchProviderConfig()) is True

        backend = registration.factory(
            object(),  # type: ignore[arg-type]
            WebSearchProviderConfig(),
            BackendTuning(),
        )

        assert isinstance(backend, expected_type)

    def test_google_cse_is_unavailable_without_credentials(self) -> None:
        registration = PROVIDER_REGISTRY["google_cse"]

        assert registration.is_available(WebSearchProviderConfig()) is False
        assert (
            registration.is_available(
                WebSearchProviderConfig(google_cse_api_key="key")
            )
            is False
        )
        assert (
            registration.is_available(
                WebSearchProviderConfig(
                    google_cse_search_engine_id="cx"
                )
            )
            is False
        )

    def test_google_cse_is_available_with_both_credentials(self) -> None:
        registration = PROVIDER_REGISTRY["google_cse"]
        config = WebSearchProviderConfig(
            google_cse_api_key="key",
            google_cse_search_engine_id="cx",
        )

        assert registration.is_available(config) is True

        backend = registration.factory(
            object(), config, BackendTuning()  # type: ignore[arg-type]
        )

        assert isinstance(backend, GoogleCseSearchBackend)


class TestBuildSearchBackend:
    def test_single_provider_is_unwrapped_not_wrapped_in_failover(
        self,
    ) -> None:
        """
        Backward compatibility: when only one provider is
        configured/available, `build_search_backend()` must return
        that provider's own backend directly, so its exceptions
        propagate exactly as they always have - not wrapped in
        `WebSearchAllProvidersFailedError`.
        """

        config = WebSearchProviderConfig(
            default_provider="only", provider_order=("only",)
        )
        built = _FakeBackend(error=WebSearchTimeoutError("timed out"))

        backend = build_search_backend(
            config,
            transport=object(),  # type: ignore[arg-type]
            registry={
                "only": ProviderRegistration(
                    name="only",
                    factory=lambda transport, cfg, tuning: built,
                )
            },
        )

        assert backend is built

    def test_multiple_providers_are_wrapped_in_failover_order(self) -> None:
        config = WebSearchProviderConfig(
            default_provider="duckduckgo",
            provider_order=("duckduckgo", "bing", "google"),
        )

        built: dict[str, _FakeBackend] = {
            "duckduckgo": _FakeBackend(
                error=WebSearchTimeoutError("timed out")
            ),
            "bing": _FakeBackend(result=SUCCESS_RESULT),
            "google": _FakeBackend(result=SUCCESS_RESULT),
        }

        backend = build_search_backend(
            config,
            transport=object(),  # type: ignore[arg-type]
            registry={
                name: ProviderRegistration(
                    name=name,
                    factory=(
                        lambda transport, cfg, tuning, _name=name: built[
                            _name
                        ]
                    ),
                )
                for name in built
            },
        )

        assert isinstance(backend, FailoverSearchBackend)

        results = backend.search("parika", max_results=5)

        assert results == SUCCESS_RESULT
        assert built["duckduckgo"].calls == [("parika", 5)]
        assert built["bing"].calls == [("parika", 5)]
        assert built["google"].calls == []

    def test_unrecognized_provider_is_skipped(self) -> None:
        config = WebSearchProviderConfig(
            default_provider="typo_provider",
            provider_order=("typo_provider", "duckduckgo"),
        )
        built = _FakeBackend(result=SUCCESS_RESULT)

        backend = build_search_backend(
            config,
            transport=object(),  # type: ignore[arg-type]
            registry={
                "duckduckgo": ProviderRegistration(
                    name="duckduckgo",
                    factory=lambda transport, cfg, tuning: built,
                )
            },
        )

        assert backend is built

    def test_unavailable_provider_is_skipped(self) -> None:
        """
        A recognized provider that reports itself unavailable (e.g.
        Google Custom Search without credentials) must be skipped
        exactly like an unrecognized one - never attempted.
        """

        config = WebSearchProviderConfig(
            default_provider="google_cse",
            provider_order=("google_cse", "duckduckgo"),
        )
        never_built = _FakeBackend(result=SUCCESS_RESULT)
        fallback = _FakeBackend(result=SUCCESS_RESULT)

        def _fail_if_called(transport, cfg, tuning):
            raise AssertionError(
                "an unavailable provider's factory must never be called"
            )

        backend = build_search_backend(
            config,
            transport=object(),  # type: ignore[arg-type]
            registry={
                "google_cse": ProviderRegistration(
                    name="google_cse",
                    factory=_fail_if_called,
                    is_available=lambda cfg: False,
                ),
                "duckduckgo": ProviderRegistration(
                    name="duckduckgo",
                    factory=lambda transport, cfg, tuning: fallback,
                ),
            },
        )

        assert backend is fallback
        assert never_built.calls == []

    def test_raises_when_no_provider_is_recognized(self) -> None:
        config = WebSearchProviderConfig(
            default_provider="nonexistent",
            provider_order=("nonexistent",),
        )

        with pytest.raises(ValueError):
            build_search_backend(
                config,
                transport=object(),  # type: ignore[arg-type]
                registry={},
            )

    def test_raises_when_every_recognized_provider_is_unavailable(
        self,
    ) -> None:
        config = WebSearchProviderConfig(
            default_provider="google_cse",
            provider_order=("google_cse",),
        )

        with pytest.raises(ValueError):
            build_search_backend(
                config,
                transport=object(),  # type: ignore[arg-type]
                registry={
                    "google_cse": ProviderRegistration(
                        name="google_cse",
                        factory=lambda transport, cfg, tuning: _FakeBackend(
                            result=SUCCESS_RESULT
                        ),
                        is_available=lambda cfg: False,
                    )
                },
            )

    def test_bare_default_config_builds_a_single_unwrapped_backend(
        self,
    ) -> None:
        """
        `WebSearchProviderConfig()`'s own bare dataclass default is
        deliberately a single provider (see `config.DEFAULT_PROVIDER_ORDER`'s
        docstring), so building against it directly - as any caller
        that never supplies a `Configuration` does - never fans out
        into a multi-provider failover chain.
        """

        config = WebSearchProviderConfig()

        backend = build_search_backend(
            config,
            transport=object(),  # type: ignore[arg-type]
        )

        assert isinstance(backend, GoogleHtmlSearchBackend)

    def test_default_registry_builds_a_real_failover_across_every_provider(
        self,
    ) -> None:
        """
        End-to-end sanity check using the real `PROVIDER_REGISTRY`
        (not a scripted one): `config/defaults.toml`'s actual, full
        `provider_order` builds a `FailoverSearchBackend` spanning
        every no-configuration provider, skipping `google_cse`
        automatically.
        """

        config = WebSearchProviderConfig(
            default_provider="google",
            provider_order=(
                "google",
                "bing",
                "duckduckgo",
                "mojeek",
                "qwant",
                "google_cse",
            ),
        )

        backend = build_search_backend(
            config,
            transport=object(),  # type: ignore[arg-type]
        )

        assert isinstance(backend, FailoverSearchBackend)
