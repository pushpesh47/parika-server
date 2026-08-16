"""
PARIKA Currency Tool - Provider Configuration

Reads the `[currency]` TOML section through the existing
`Configuration` Core component and exposes it as a small, typed,
read-only snapshot, following the same pattern as
`parika/tools/web_search/config.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

DEFAULT_PROVIDER = "frankfurter"
"""
Frankfurter is the default provider: open-source, self-hostable, no
request quota, and sourced directly from named central banks. See
`docs/architecture/Tools_Expansion_Phase1_Plan.md` section 3.3 for
the full comparison against `open_er_api`.
"""

DEFAULT_PROVIDER_ORDER: tuple[str, ...] = ("frankfurter", "open_er_api")
"""
`open_er_api` is retained only as an automatic failover for pairs
Frankfurter's ECB-anchored coverage does not include, or when
Frankfurter itself is unreachable.
"""

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.5


@dataclass(frozen=True, slots=True, kw_only=True)
class CurrencyToolConfig:
    """
    Immutable, typed snapshot of `[currency]` configuration.
    """

    enabled: bool = True
    default_provider: str = DEFAULT_PROVIDER
    provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS

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


def load_currency_config(
    configuration: Configuration | None,
) -> CurrencyToolConfig:
    """
    Build a `CurrencyToolConfig` snapshot from `Configuration`.

    Args:
        configuration:
            The Core `Configuration` component. When `None`, every
            value falls back to its built-in default.

    Returns:
        The resolved, immutable configuration snapshot.
    """

    if configuration is None:
        return CurrencyToolConfig()

    provider_order_raw = configuration.get(
        "currency.provider_order", list(DEFAULT_PROVIDER_ORDER)
    )

    if isinstance(provider_order_raw, (list, tuple)):
        provider_order = tuple(str(name) for name in provider_order_raw)
    else:
        provider_order = DEFAULT_PROVIDER_ORDER

    default_provider = str(
        configuration.get(
            "currency.default_provider",
            provider_order[0] if provider_order else DEFAULT_PROVIDER,
        )
    )

    return CurrencyToolConfig(
        enabled=bool(configuration.get("currency.enabled", True)),
        default_provider=default_provider,
        provider_order=provider_order,
        timeout_seconds=float(
            configuration.get(
                "currency.request_timeout_seconds", DEFAULT_TIMEOUT_SECONDS
            )
        ),
        max_attempts=int(
            configuration.get("currency.max_attempts", DEFAULT_MAX_ATTEMPTS)
        ),
        backoff_seconds=float(
            configuration.get(
                "currency.backoff_seconds", DEFAULT_BACKOFF_SECONDS
            )
        ),
    )
