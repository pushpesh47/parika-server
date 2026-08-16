"""
PARIKA Expense Tool - Configuration

Reads the `[expense]` TOML section through the existing
`Configuration` Core component, following the same pattern as
`parika/tools/weather/config.py`/`parika/tools/currency/config.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

from .model import DEFAULT_EXPENSE_CATEGORIES, DEFAULT_EXPENSE_CURRENCY

DEFAULT_MAX_LIST_RESULTS = 200
DEFAULT_LIST_LIMIT = 50
DEFAULT_LARGEST_COUNT = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseToolConfig:
    """
    Immutable, typed snapshot of `[expense]` configuration.
    """

    enabled: bool = True
    default_currency: str = DEFAULT_EXPENSE_CURRENCY
    suggested_categories: tuple[str, ...] = DEFAULT_EXPENSE_CATEGORIES
    default_list_limit: int = DEFAULT_LIST_LIMIT
    max_list_results: int = DEFAULT_MAX_LIST_RESULTS
    default_largest_count: int = DEFAULT_LARGEST_COUNT


def load_expense_config(configuration: Configuration | None) -> ExpenseToolConfig:
    """
    Build an `ExpenseToolConfig` snapshot from `Configuration`.

    Args:
        configuration:
            The Core `Configuration` component. When `None`, every
            value falls back to its built-in default.
    """

    if configuration is None:
        return ExpenseToolConfig()

    categories_raw = configuration.get(
        "expense.categories", list(DEFAULT_EXPENSE_CATEGORIES)
    )
    categories = (
        tuple(str(category) for category in categories_raw)
        if isinstance(categories_raw, (list, tuple))
        else DEFAULT_EXPENSE_CATEGORIES
    )

    return ExpenseToolConfig(
        enabled=bool(configuration.get("expense.enabled", True)),
        default_currency=str(
            configuration.get("expense.default_currency", DEFAULT_EXPENSE_CURRENCY)
        ),
        suggested_categories=categories,
        default_list_limit=int(
            configuration.get("expense.default_list_limit", DEFAULT_LIST_LIMIT)
        ),
        max_list_results=int(
            configuration.get("expense.max_list_results", DEFAULT_MAX_LIST_RESULTS)
        ),
        default_largest_count=int(
            configuration.get(
                "expense.default_largest_count", DEFAULT_LARGEST_COUNT
            )
        ),
    )
