"""
PARIKA Expense Tool Exceptions

Defines the exception hierarchy used by the Expense Tool/Service.

All Expense Tool exceptions derive from `ExpenseToolError` so that
`ToolManager` can uniformly wrap them as `ToolExecutionError`, exactly
like every other Tool in PARIKA (see `currency` and `weather`).

Class names are deliberately chosen to line up with
`parika/api/errors.py`'s existing suffix-matching table wherever
possible, so the direct (non-Tool) Expense API endpoints map to the
correct HTTP status with zero changes to that table:

    ExpenseNotFoundError    -> "NotFoundError"    -> 404
    ExpenseInvalidRequestError -> "InvalidRequestError" -> 400

`ExpenseAmbiguousMatchError` has no existing suffix-mapped equivalent
anywhere in PARIKA; `parika/api/errors.py` adds exactly one new table
entry (`"AmbiguousMatchError"`) for it (see that module's docstring
for why this is an additive, non-breaking change).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Expense


class ExpenseToolError(Exception):
    """
    Base exception for all Expense Tool/Service errors.
    """


class ExpenseInvalidRequestError(ExpenseToolError):
    """
    Raised when a request is missing a required field, or supplies an
    invalid one: a missing/blank item, a non-positive or unparseable
    amount, an invalid currency code, an unparseable date, or an
    invalid period/filter combination.
    """


class ExpenseNotFoundError(ExpenseToolError):
    """
    Raised when a specific expense id does not exist, or when a
    match-based lookup (used by natural-language update/delete
    requests that have no id) finds zero candidates.
    """


class ExpensePersistenceError(ExpenseToolError):
    """
    Raised when the underlying SQLite storage fails unexpectedly.
    """


class ExpenseAmbiguousMatchError(ExpenseToolError):
    """
    Raised when a match-based update/delete (identifying a target
    expense by description rather than by id) matches more than one
    record and the caller did not explicitly request bulk deletion.

    Carries the full set of matching candidates so a caller can
    present them for clarification. `ExpenseToolDriver` catches this
    directly for the Tool-calling path and returns a normal,
    non-error `ToolResponse` describing the ambiguity (see its own
    module docstring) - it only ever propagates as an exception on the
    direct API path, where `parika/api/errors.py` maps it to HTTP 409.
    """

    def __init__(
        self, message: str, *, candidates: Sequence["Expense"]
    ) -> None:
        super().__init__(message)
        self.candidates: tuple["Expense", ...] = tuple(candidates)
