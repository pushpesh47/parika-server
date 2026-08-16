"""
PARIKA Currency Tool package.

Implements the `currency.exchange_rate` and `currency.convert`
Capabilities using Frankfurter (https://api.frankfurter.dev) as the
primary provider, with automatic failover to open.er-api.com - both
free and keyless.

Public exports provide everything needed to register these Tools with
ToolManager, either directly or through the Currency Module.
"""

from __future__ import annotations

from .backend_failover import FailoverRateBackend
from .backend_frankfurter import FrankfurterRateBackend
from .backend_open_er_api import OpenErApiRateBackend
from .config import CurrencyToolConfig, load_currency_config
from .driver import CurrencyToolDriver
from .exceptions import (
    CurrencyAllProvidersFailedError,
    CurrencyNetworkError,
    CurrencyProviderUnavailableError,
    CurrencyTimeoutError,
    CurrencyToolError,
    InvalidCurrencyArgumentError,
    UnsupportedCurrencyPairError,
)
from .manifest import (
    CURRENCY_CAPABILITY_CONVERT,
    CURRENCY_CAPABILITY_EXCHANGE_RATE,
    CURRENCY_TOOL_ID_CONVERT,
    CURRENCY_TOOL_ID_EXCHANGE_RATE,
    CURRENCY_TOOL_VERSION,
    CurrencyMode,
    create_currency_convert_tool,
    create_currency_exchange_rate_tool,
)
from .protocol import RateBackend
from .provider_registry import PROVIDER_REGISTRY, build_rate_backend
from .transport import HttpResponse, HttpTransport, UrllibHttpTransport

__all__ = [
    "CURRENCY_CAPABILITY_CONVERT",
    "CURRENCY_CAPABILITY_EXCHANGE_RATE",
    "CURRENCY_TOOL_ID_CONVERT",
    "CURRENCY_TOOL_ID_EXCHANGE_RATE",
    "CURRENCY_TOOL_VERSION",
    "PROVIDER_REGISTRY",
    "CurrencyAllProvidersFailedError",
    "CurrencyMode",
    "CurrencyNetworkError",
    "CurrencyProviderUnavailableError",
    "CurrencyTimeoutError",
    "CurrencyToolConfig",
    "CurrencyToolDriver",
    "CurrencyToolError",
    "FailoverRateBackend",
    "FrankfurterRateBackend",
    "HttpResponse",
    "HttpTransport",
    "InvalidCurrencyArgumentError",
    "OpenErApiRateBackend",
    "RateBackend",
    "UnsupportedCurrencyPairError",
    "UrllibHttpTransport",
    "build_rate_backend",
    "create_currency_convert_tool",
    "create_currency_exchange_rate_tool",
    "load_currency_config",
]
