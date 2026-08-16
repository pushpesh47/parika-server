"""
PARIKA Currency Tool - Rate Provider Failover

Defines `FailoverRateBackend`, a `RateBackend` that tries an ordered
sequence of other `RateBackend`s, falling over to the next one
whenever the current one errors, until one succeeds, or raising
`CurrencyAllProvidersFailedError` once every provider has failed.

Mirrors `parika/tools/web_search/search_backend_failover.py`'s
design exactly, retargeted at currency rate lookups.
"""

from __future__ import annotations

from collections.abc import Sequence

from parika.core.logger.logger import Logger

from .exceptions import (
    CurrencyAllProvidersFailedError,
    InvalidCurrencyArgumentError,
)
from .protocol import RateBackend


class FailoverRateBackend:
    """
    A `RateBackend` that tries an ordered sequence of other
    `RateBackend`s, falling over to the next one whenever the current
    one raises.

    A request's own validation errors (`InvalidCurrencyArgumentError`)
    are never treated as a provider failure - every provider would
    reject the exact same invalid input identically - and propagate
    immediately instead.
    """

    def __init__(
        self,
        backends: Sequence[tuple[str, RateBackend]],
        *,
        logger: Logger | None = None,
    ) -> None:
        if not backends:
            raise ValueError(
                "FailoverRateBackend requires at least one backend."
            )

        self._backends = tuple(backends)
        self._logger = logger.get_logger(__name__) if logger else None

    def get_rate(self, base: str, quote: str) -> float:
        """
        Return the exchange rate from `base` to `quote`, trying each
        configured provider in order until one succeeds.

        Raises:
            InvalidCurrencyArgumentError:
                If `base`/`quote` is invalid - raised immediately.

            CurrencyAllProvidersFailedError:
                If every configured provider failed.
        """

        failures: list[tuple[str, Exception]] = []

        for name, backend in self._backends:
            try:
                return backend.get_rate(base, quote)

            except InvalidCurrencyArgumentError:
                raise

            except Exception as ex:  # noqa: BLE001 - failover boundary
                failures.append((name, ex))

                if self._logger is not None:
                    self._logger.warning(
                        "Currency rate provider '%s' failed (%s); "
                        "trying the next configured provider.",
                        name,
                        ex,
                    )

        summary = "; ".join(f"{name}: {error}" for name, error in failures)

        raise CurrencyAllProvidersFailedError(
            f"Every configured currency rate provider failed: {summary}"
        )
