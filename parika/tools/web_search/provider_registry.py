"""
PARIKA Web Search Tool - Provider Registry

The single place responsible for creating every search provider
backend instance. No other module ever instantiates a
`search_backend_<provider>.py` class directly (except tests, and
`WebSearchModuleDriver`'s explicit `search_backend` override, which
bypasses provider selection entirely by design).

Adding a future provider
-------------------------
1. Implement the `SearchBackend` protocol (`protocol.py`) in a new
   module named `search_backend_<provider>.py` -
   `search_backend_duckduckgo.py`, `search_backend_google.py`,
   `search_backend_bing.py`, `search_backend_mojeek.py`,
   `search_backend_qwant.py`, and `search_backend_google_cse.py` are
   worked examples. Every provider backend file must follow this
   naming convention, so every provider stays grouped together
   alphabetically in a directory listing.
2. Register one `ProviderRegistration` for it in `PROVIDER_REGISTRY`
   below, keyed by the name operators will use in configuration. If
   the provider requires configuration to function (an API key, for
   example), also supply `is_available` so it is automatically
   skipped - never attempted - when unconfigured.
3. Add that name to `[web_search].provider_order` (and optionally set
   it as `[web_search].default_provider`) in `config/defaults.toml`
   or any higher-precedence configuration layer. If the new provider
   needs its own configuration, add a `[web_search.<provider>]`
   section and read it in `config.py`'s `WebSearchProviderConfig`/
   `load_web_search_config()` - only providers that actually need
   configuration get a section of their own (see `config.py`).

No other code needs to change: `WebSearchModuleDriver` builds its
default backend purely from `WebSearchProviderConfig` and this
registry, and `FailoverSearchBackend` (`search_backend_failover.py`)
itself has no knowledge of any specific provider - this module is the
only place provider-specific construction logic is ever allowed to
live.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from parika.core.logger.logger import Logger

from .config import WebSearchProviderConfig
from .protocol import SearchBackend
from .search_backend_bing import BingHtmlSearchBackend
from .search_backend_duckduckgo import DuckDuckGoHtmlSearchBackend
from .search_backend_failover import FailoverSearchBackend
from .search_backend_google import GoogleHtmlSearchBackend
from .search_backend_google_cse import GoogleCseSearchBackend
from .search_backend_mojeek import MojeekHtmlSearchBackend
from .search_backend_parallel_mcp import ParallelMcpSearchBackend
from .search_backend_qwant import QwantHtmlSearchBackend
from .transport import HttpTransport


@dataclass(frozen=True, slots=True, kw_only=True)
class BackendTuning:
    """
    Network tuning shared across every provider a `build_search_backend()`
    call constructs - the same three knobs `WebSearchModuleDriver`
    has always exposed for its (previously singular) default backend.
    """

    timeout_seconds: float = 10.0
    max_attempts: int = 3
    backoff_seconds: float = 0.5


BackendFactory = Callable[
    [HttpTransport, WebSearchProviderConfig, BackendTuning], SearchBackend
]
AvailabilityCheck = Callable[[WebSearchProviderConfig], bool]


def _always_available(config: WebSearchProviderConfig) -> bool:
    """
    Default `ProviderRegistration.is_available` for every provider
    that needs no configuration of its own.
    """

    return True


def _google_cse_is_available(config: WebSearchProviderConfig) -> bool:
    """
    Google Custom Search requires both an API key and a Search Engine
    ID; without either, a request is guaranteed to fail (HTTP
    400/403), so it must never even be attempted.
    """

    return bool(config.google_cse_api_key) and bool(
        config.google_cse_search_engine_id
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderRegistration:
    """
    Everything the registry needs to know about one search provider:
    how to build it, and how to tell whether it is currently usable.
    """

    name: str
    factory: BackendFactory
    is_available: AvailabilityCheck = _always_available


PROVIDER_REGISTRY: Mapping[str, ProviderRegistration] = {
    "google": ProviderRegistration(
        name="google",
        factory=lambda transport, config, tuning: GoogleHtmlSearchBackend(
            transport,
            timeout_seconds=tuning.timeout_seconds,
            max_attempts=tuning.max_attempts,
            backoff_seconds=tuning.backoff_seconds,
        ),
    ),
    "bing": ProviderRegistration(
        name="bing",
        factory=lambda transport, config, tuning: BingHtmlSearchBackend(
            transport,
            timeout_seconds=tuning.timeout_seconds,
            max_attempts=tuning.max_attempts,
            backoff_seconds=tuning.backoff_seconds,
        ),
    ),
    "duckduckgo": ProviderRegistration(
        name="duckduckgo",
        factory=lambda transport, config, tuning: DuckDuckGoHtmlSearchBackend(
            transport,
            timeout_seconds=tuning.timeout_seconds,
            max_attempts=tuning.max_attempts,
            backoff_seconds=tuning.backoff_seconds,
        ),
    ),
    "mojeek": ProviderRegistration(
        name="mojeek",
        factory=lambda transport, config, tuning: MojeekHtmlSearchBackend(
            transport,
            timeout_seconds=tuning.timeout_seconds,
            max_attempts=tuning.max_attempts,
            backoff_seconds=tuning.backoff_seconds,
        ),
    ),
    "qwant": ProviderRegistration(
        name="qwant",
        factory=lambda transport, config, tuning: QwantHtmlSearchBackend(
            transport,
            timeout_seconds=tuning.timeout_seconds,
            max_attempts=tuning.max_attempts,
            backoff_seconds=tuning.backoff_seconds,
        ),
    ),
    "parallel_mcp": ProviderRegistration(
        name="parallel_mcp",
        factory=lambda transport, config, tuning: ParallelMcpSearchBackend(
            transport,
            timeout_seconds=tuning.timeout_seconds,
            max_attempts=tuning.max_attempts,
            backoff_seconds=tuning.backoff_seconds,
        ),
    ),
    "google_cse": ProviderRegistration(
        name="google_cse",
        factory=lambda transport, config, tuning: GoogleCseSearchBackend(
            transport,
            api_key=config.google_cse_api_key,
            search_engine_id=config.google_cse_search_engine_id,
            timeout_seconds=tuning.timeout_seconds,
            max_attempts=tuning.max_attempts,
            backoff_seconds=tuning.backoff_seconds,
        ),
        is_available=_google_cse_is_available,
    ),
}
"""
Every search provider PARIKA knows how to build, keyed by the name
used in `[web_search]` configuration. See this module's docstring for
how to register a new one.
"""


def build_search_backend(
    config: WebSearchProviderConfig,
    transport: HttpTransport,
    *,
    tuning: BackendTuning = BackendTuning(),
    logger: Logger | None = None,
    registry: Mapping[str, ProviderRegistration] = PROVIDER_REGISTRY,
) -> SearchBackend:
    """
    Build the configured `SearchBackend`, wrapping every recognized,
    *available* provider in `config.failover_order()` behind a
    `FailoverSearchBackend`.

    An unrecognized provider name, or one that is recognized but not
    currently available (e.g. `google_cse` without credentials), is
    skipped (and logged, when `logger` is supplied) rather than
    raising, so one misconfigured or unconfigured provider never
    disables every other configured provider.

    Args:
        config:
            Resolved `[web_search]` configuration (see
            `load_web_search_config()`).

        transport:
            `HttpTransport` every constructed backend shares.

        tuning:
            Network tuning (timeout/attempts/backoff) shared by every
            constructed backend.

        logger:
            Optional PARIKA Logger component, forwarded to the
            resulting `FailoverSearchBackend` and used to report any
            unrecognized or unavailable provider name.

        registry:
            Provider name -> `ProviderRegistration` mapping. Defaults
            to `PROVIDER_REGISTRY`; overridable for tests.

    Returns:
        A `SearchBackend`: the single available configured provider's
        backend directly (unwrapped) when only one is
        configured/recognized/available - so that provider's own
        exceptions propagate exactly as they always have, unchanged -
        or a `FailoverSearchBackend` wrapping every available
        configured provider, in `config.failover_order()`, when two
        or more are available.

    Raises:
        ValueError:
            If no configured provider name is both recognized and
            currently available.
    """

    log = logger.get_logger(__name__) if logger else None
    backends: list[tuple[str, SearchBackend]] = []

    for name in config.failover_order():
        registration = registry.get(name)

        if registration is None:
            if log is not None:
                log.warning(
                    "Unrecognized web search provider '%s' in "
                    "configuration; skipping it.",
                    name,
                )
            continue

        if not registration.is_available(config):
            if log is not None:
                log.info(
                    "Web search provider '%s' is not configured/"
                    "available; skipping it.",
                    name,
                )
            continue

        backends.append((name, registration.factory(transport, config, tuning)))

    if not backends:
        raise ValueError(
            "No usable web search provider in configuration: "
            f"{config.failover_order()!r}."
        )

    if len(backends) == 1:
        return backends[0][1]

    return FailoverSearchBackend(backends, logger=logger)
