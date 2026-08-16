"""
PARIKA Expense Tool - Filters

Defines the one, shared `ExpenseFilter` used by every read/aggregate
operation (`list`, `summarize`, `compare`) and by match-based
update/delete (locating a target expense by description rather than
by id - see `service.py`).
"""

from __future__ import annotations

from dataclasses import dataclass

from .periods import Period


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseFilter:
    """
    Immutable combination of filter criteria.

    Every field is optional; an all-`None` filter matches every
    expense. Combining fields is always an AND (e.g. `period` +
    `category` + `item_contains` narrows on all three at once).
    """

    period: Period | None = None
    category: str | None = None
    item_contains: str | None = None
    min_amount_minor: int | None = None
    max_amount_minor: int | None = None
