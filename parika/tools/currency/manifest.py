"""
PARIKA Currency Tool - Manifest

Defines the static Tool metadata describing the Currency Tool's two
Capabilities.

Like the Weather Tool, `currency.exchange_rate` and
`currency.convert` are each registered as their own Tool
(`CurrencyToolDriver` bound to one `CurrencyMode` per instance),
since `ToolRequest` carries no capability identifier for a single
Tool to dispatch on. See `parika/tools/filesystem/manifest.py`'s
module docstring for the full reasoning.

This module owns Tool creation. ToolManager only registers and stores
the Tool instances produced here; it does not create Tool objects
itself.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from parika.core.tool_manager.tool import Tool

CURRENCY_TOOL_VERSION = "1.0.0"


class CurrencyMode(StrEnum):
    """
    The two Capabilities the Currency Tool implements.
    """

    EXCHANGE_RATE = "exchange_rate"
    CONVERT = "convert"


CURRENCY_CAPABILITY_EXCHANGE_RATE = "currency.exchange_rate"
CURRENCY_CAPABILITY_CONVERT = "currency.convert"

CURRENCY_TOOL_ID_EXCHANGE_RATE = "tool.currency_exchange_rate"
CURRENCY_TOOL_ID_CONVERT = "tool.currency_convert"

_CURRENCY_FAILURE_SEMANTICS = (
    "If a currency code is not recognized, ask the user for "
    "clarification (e.g. the standard 3-letter code) rather than "
    "guessing one."
)

CURRENCY_TOOL_AFFORDANCES: Mapping[str, Mapping[str, Any]] = {
    CURRENCY_CAPABILITY_EXCHANGE_RATE: {
        "description": "Get the current exchange rate between two currencies.",
        "purpose": (
            "Provides the real current exchange rate between two "
            "currencies, since rates change constantly and your own "
            "knowledge is not current."
        ),
        "use_when": "the user asks what the exchange rate is between two currencies.",
        "avoid_when": (
            "the rate is already available from the conversation or "
            "an earlier Tool result in this conversation."
        ),
        "requires": "the source currency code and the destination currency code.",
        "result_semantics": (
            "Returns a numeric rate. State it naturally as part of "
            "your answer; do not describe the raw response structure."
        ),
        "failure_semantics": _CURRENCY_FAILURE_SEMANTICS,
        "parameters": {
            "type": "object",
            "properties": {
                "base": {"type": "string", "description": "3-letter base currency code, e.g. 'USD'."},
                "quote": {"type": "string", "description": "3-letter quote currency code, e.g. 'EUR'."},
            },
            "required": ["base", "quote"],
        },
    },
    CURRENCY_CAPABILITY_CONVERT: {
        "description": "Convert an amount from one currency to another.",
        "purpose": (
            "Provides an accurate currency conversion using the "
            "real current exchange rate."
        ),
        "use_when": "the user asks to convert a specific amount from one currency to another.",
        "avoid_when": (
            "no specific amount was given to convert - use the "
            "Exchange Rate capability instead when only the rate "
            "itself is being asked about."
        ),
        "requires": "the source currency code, the destination currency code, and the amount to convert.",
        "result_semantics": (
            "Returns the converted amount. State it naturally as "
            "part of your answer; do not describe the raw response "
            "structure."
        ),
        "failure_semantics": _CURRENCY_FAILURE_SEMANTICS,
        "parameters": {
            "type": "object",
            "properties": {
                "base": {"type": "string", "description": "3-letter source currency code, e.g. 'USD'."},
                "quote": {"type": "string", "description": "3-letter target currency code, e.g. 'EUR'."},
                "amount": {"type": "number", "description": "Amount, in base currency, to convert."},
            },
            "required": ["base", "quote", "amount"],
        },
    },
}
"""
Tool Affordance Contracts for `currency.exchange_rate`/
`currency.convert`, registered as each Capability's
`CapabilityDefinition.metadata["tool_affordance"]` (see
`parika/modules/currency/driver.py`).
"""


def create_currency_exchange_rate_tool() -> Tool:
    """
    Build the immutable Tool descriptor for `currency.exchange_rate`.
    """

    return Tool(
        id=CURRENCY_TOOL_ID_EXCHANGE_RATE,
        name="Currency Exchange Rate",
        version=CURRENCY_TOOL_VERSION,
        description=(
            "Returns the current exchange rate between two "
            "currencies."
        ),
        capabilities=(CURRENCY_CAPABILITY_EXCHANGE_RATE,),
    )


def create_currency_convert_tool() -> Tool:
    """
    Build the immutable Tool descriptor for `currency.convert`.
    """

    return Tool(
        id=CURRENCY_TOOL_ID_CONVERT,
        name="Currency Convert",
        version=CURRENCY_TOOL_VERSION,
        description=(
            "Converts an amount from one currency to another using "
            "the current exchange rate."
        ),
        capabilities=(CURRENCY_CAPABILITY_CONVERT,),
    )
