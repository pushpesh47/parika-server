"""
PARIKA Currency Tool - Provider Registry

The single place responsible for creating every currency rate
provider backend instance, mirroring
`parika/tools/web_search/provider_registry.py`'s role exactly.

Adding a future provider
-------------------------
1. Implement the `RateBackend` protocol (`protocol.py`) in a new
   module named `backend_<provider>.py`.
2. Register one `ProviderRegistration` for it in `PROVIDER_REGISTRY`
   below, keyed by the name operators will use in configuration.
3. Add that name to `[currency].provider_order` in
   `config/defaults.toml`.

No other code needs to change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from parika.core.logger.logger import Logger

from .backend_failover import FailoverRateBackend
from .backend_frankfurter import FrankfurterRateBackend
from .backend_open_er_api import OpenErApiRateBackend
from .config import CurrencyToolConfig
from .protocol import RateBackend
from .transport import HttpTransport


@dataclass(frozen=True, slots=True, kw_only=True)
class BackendTuning:
    """
    Network tuning shared across every provider a
    `build_rate_backend()` call constructs.
    """

    timeout_seconds: float = 10.0
    max_attempts: int = 3
    backoff_seconds: float = 0.5


BackendFactory = Callable[[HttpTransport, BackendTuning], RateBackend]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderRegistration:
    """
    Everything the registry needs to know about one currency rate
    provider: how to build it.
    """

    name: str
    factory: BackendFactory


PROVIDER_REGISTRY: Mapping[str, ProviderRegistration] = {
    "frankfurter": ProviderRegistration(
        name="frankfurter",
        factory=lambda transport, tuning: FrankfurterRateBackend(
            transport,
            timeout_seconds=tuning.timeout_seconds,
            max_attempts=tuning.max_attempts,
            backoff_seconds=tuning.backoff_seconds,
        ),
    ),
    "open_er_api": ProviderRegistration(
        name="open_er_api",
        factory=lambda transport, tuning: OpenErApiRateBackend(
            transport,
            timeout_seconds=tuning.timeout_seconds,
            max_attempts=tuning.max_attempts,
            backoff_seconds=tuning.backoff_seconds,
        ),
    ),
}
"""
Every currency rate provider PARIKA knows how to build, keyed by the
name used in `[currency]` configuration.
"""


def build_rate_backend(
    config: CurrencyToolConfig,
    transport: HttpTransport,
    *,
    tuning: BackendTuning = BackendTuning(),
    logger: Logger | None = None,
    registry: Mapping[str, ProviderRegistration] = PROVIDER_REGISTRY,
) -> RateBackend:
    """
    Build the configured `RateBackend`, wrapping every recognized
    provider in `config.failover_order()` behind a
    `FailoverRateBackend`.

    Returns:
        The single configured provider's backend directly (unwrapped)
        when only one is configured/recognized, or a
        `FailoverRateBackend` wrapping every configured provider, in
        `config.failover_order()`, when two or more are configured.

    Raises:
        ValueError:
            If no configured provider name is recognized.
    """

    log = logger.get_logger(__name__) if logger else None
    backends: list[tuple[str, RateBackend]] = []

    for name in config.failover_order():
        registration = registry.get(name)

        if registration is None:
            if log is not None:
                log.warning(
                    "Unrecognized currency rate provider '%s' in "
                    "configuration; skipping it.",
                    name,
                )
            continue

        backends.append((name, registration.factory(transport, tuning)))

    if not backends:
        raise ValueError(
            "No usable currency rate provider in configuration: "
            f"{config.failover_order()!r}."
        )

    if len(backends) == 1:
        return backends[0][1]

    return FailoverRateBackend(backends, logger=logger)
