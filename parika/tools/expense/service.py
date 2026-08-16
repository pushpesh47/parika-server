"""
PARIKA Expense Tool - Service

`ExpenseService` is the single, shared domain-logic object behind
every Expense Management entry point: the seven
`ExpenseToolDriver` instances the Planner/Brain reach through
natural-language tool-calling, *and* the direct
`GET/POST/PATCH/DELETE /api/v1/expenses...` handlers the Web Client
calls for structured CRUD (see
`docs/architecture/adr/0003-expense-management.md`, Decision 5). Both
entry points operate on exactly one `ExpenseService` instance
(constructed once by `ExpenseModuleDriver` and additionally exposed
through `ServiceContainer` for the API layer), so a record added
through natural language is immediately visible to the Web Client and
vice versa - there is no second, competing data path.

This module contains every business rule the requirement specifies:
validation (missing item, non-positive amount, invalid currency/date),
default-to-today date resolution, and - critically - the ambiguity
safety rules for match-based update/delete ("do not silently modify
or delete the wrong record").
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .calculations import (
    ExpenseSummary,
    PeriodComparison,
    PeriodComparisonSide,
    build_category_breakdown,
    compare_totals,
)
from .config import ExpenseToolConfig
from .dates import parse_expense_date
from .events import (
    EXPENSE_CREATED_EVENT,
    EXPENSE_DELETED_EVENT,
    EXPENSE_UPDATED_EVENT,
    ExpenseCreated,
    ExpenseDeleted,
    ExpenseUpdated,
)
from .exceptions import ExpenseAmbiguousMatchError, ExpenseNotFoundError, ExpenseInvalidRequestError, ExpensePersistenceError
from .filters import ExpenseFilter
from .model import Expense
from .money import to_minor_units, validate_currency_code
from .storage import ExpenseStorage

_UNSET = object()
"""Sentinel distinguishing "field not supplied" from "field explicitly cleared to None" on `update_by_id`."""


def _resolve_expense_date(value: object, *, today: date) -> date:
    if value is None:
        return today
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return parse_expense_date(value, today=today)
    raise ExpenseInvalidRequestError(
        "date must be a string (e.g. 'today', '2026-08-05') or a date value."
    )


def _clean_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


class ExpenseService:
    """
    Domain service coordinating validation, persistence, deterministic
    calculation, and event publication for personal expenses.
    """

    def __init__(
        self,
        *,
        storage: ExpenseStorage,
        event_bus: EventBus,
        logger: Logger,
        config: ExpenseToolConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._storage = storage
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)
        self._config = config
        self._clock = clock

    @property
    def config(self) -> ExpenseToolConfig:
        return self._config

    def create(
        self,
        *,
        amount: object,
        item: object,
        currency: object = None,
        category: object = None,
        expense_date: object = None,
        notes: object = None,
        today: date | None = None,
    ) -> Expense:
        """
        Add a new expense.

        Raises:
            ExpenseInvalidRequestError:
                If `item` is blank, `amount` is not a positive number,
                `currency` is not a 3-letter code, or `expense_date`
                cannot be resolved.
        """

        cleaned_item = _clean_optional_text(item)

        if cleaned_item is None:
            raise ExpenseInvalidRequestError(
                "An expense needs a non-empty item/description "
                "(e.g. 'milk', 'medicine')."
            )

        amount_minor = to_minor_units(amount)

        if amount_minor <= 0:
            raise ExpenseInvalidRequestError(
                "amount must be a positive number greater than zero."
            )

        resolved_currency = validate_currency_code(
            currency, default=self._config.default_currency
        )
        resolved_today = today if today is not None else self._clock().date()
        resolved_date = _resolve_expense_date(expense_date, today=resolved_today)
        now = self._clock()

        expense = Expense(
            id=uuid4().hex,
            amount_minor=amount_minor,
            currency=resolved_currency,
            item=cleaned_item,
            category=_clean_optional_text(category),
            expense_date=resolved_date,
            notes=_clean_optional_text(notes),
            created_at=now,
            updated_at=now,
        )

        stored = self._storage.insert(expense)

        self._event_bus.publish(
            EXPENSE_CREATED_EVENT,
            ExpenseCreated(
                expense_id=stored.id,
                amount_minor=stored.amount_minor,
                currency=stored.currency,
                item=stored.item,
                category=stored.category,
                expense_date=stored.expense_date.isoformat(),
            ),
        )
        self._logger.info(
            "Created expense %s (%s %s for '%s' on %s).",
            stored.id,
            stored.currency,
            stored.amount,
            stored.item,
            stored.expense_date.isoformat(),
        )

        return stored

    def get(self, expense_id: str) -> Expense:
        """
        Raises:
            ExpenseNotFoundError: If no expense has this id.
        """

        expense = self._storage.get(expense_id)

        if expense is None:
            raise ExpenseNotFoundError(f"No expense found with id '{expense_id}'.")

        return expense

    def list(
        self,
        expense_filter: ExpenseFilter,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[Expense, ...]:
        resolved_limit = min(
            limit if limit is not None else self._config.default_list_limit,
            self._config.max_list_results,
        )
        return self._storage.find(expense_filter, limit=resolved_limit, offset=offset)

    def find_matches(self, expense_filter: ExpenseFilter) -> tuple[Expense, ...]:
        """
        Every expense matching `expense_filter`, used to locate the
        candidate(s) for a match-based (no explicit id) update/delete.
        """

        return self._storage.find(
            expense_filter, limit=self._config.max_list_results, offset=0
        )

    def update_by_id(
        self,
        expense_id: str,
        *,
        amount: object = None,
        currency: object = None,
        item: object = None,
        category: object = _UNSET,
        expense_date: object = None,
        notes: object = _UNSET,
        today: date | None = None,
    ) -> Expense:
        """
        Update one specific, already-identified expense.

        Every field defaults to "leave unchanged" except `category`
        and `notes`, which default to the `_UNSET` sentinel so an
        explicit `None`/blank can clear them - passing nothing at all
        for either also leaves them unchanged.

        Raises:
            ExpenseNotFoundError: If `expense_id` does not exist.
            ExpenseInvalidRequestError: On an invalid new value.
        """

        existing = self.get(expense_id)
        changed_fields: list[str] = []

        new_amount_minor = existing.amount_minor
        if amount is not None:
            new_amount_minor = to_minor_units(amount)
            if new_amount_minor <= 0:
                raise ExpenseInvalidRequestError(
                    "amount must be a positive number greater than zero."
                )
            changed_fields.append("amount")

        new_currency = existing.currency
        if currency is not None:
            new_currency = validate_currency_code(currency, default=existing.currency)
            changed_fields.append("currency")

        new_item = existing.item
        if item is not None:
            cleaned = _clean_optional_text(item)
            if cleaned is None:
                raise ExpenseInvalidRequestError("item cannot be blank.")
            new_item = cleaned
            changed_fields.append("item")

        new_category = existing.category
        if category is not _UNSET:
            new_category = _clean_optional_text(category)
            changed_fields.append("category")

        new_date = existing.expense_date
        if expense_date is not None:
            resolved_today = today if today is not None else self._clock().date()
            new_date = _resolve_expense_date(expense_date, today=resolved_today)
            changed_fields.append("expense_date")

        new_notes = existing.notes
        if notes is not _UNSET:
            new_notes = _clean_optional_text(notes)
            changed_fields.append("notes")

        if not changed_fields:
            return existing

        # Build updates dict for atomic storage operation
        updates: dict[str, object] = {}
        if "amount" in changed_fields:
            updates["amount_minor"] = new_amount_minor
        if "currency" in changed_fields:
            updates["currency"] = new_currency
        if "item" in changed_fields:
            updates["item"] = new_item
        if "category" in changed_fields:
            updates["category"] = new_category
        if "expense_date" in changed_fields:
            updates["expense_date"] = new_date
        if "notes" in changed_fields:
            updates["notes"] = new_notes

        try:
            updated = self._storage.update_by_id(expense_id, updates=updates)
        except ExpensePersistenceError as ex:
            if "unknown expense" in str(ex).lower():
                raise ExpenseNotFoundError(f"No expense found with id '{expense_id}'.") from ex
            raise

        self._event_bus.publish(
            EXPENSE_UPDATED_EVENT,
            ExpenseUpdated(expense_id=expense_id, changed_fields=tuple(changed_fields)),
        )
        self._logger.info(
            "Updated expense %s (fields: %s).", expense_id, ", ".join(changed_fields)
        )

        return updated

    def update_by_match(
        self,
        expense_filter: ExpenseFilter,
        *,
        changes: dict[str, object],
        today: date | None = None,
    ) -> Expense:
        """
        Update the single expense matching `expense_filter`.

        Raises:
            ExpenseNotFoundError: If nothing matches.
            ExpenseAmbiguousMatchError:
                If more than one expense matches - the caller must
                narrow the filter or supply an explicit id instead.
        """

        # Convert changes dict to storage format
        updates: dict[str, object] = {}
        if "amount" in changes:
            updates["amount_minor"] = to_minor_units(changes["amount"])
        if "currency" in changes:
            updates["currency"] = validate_currency_code(changes["currency"], default="INR")
        if "item" in changes:
            updates["item"] = changes["item"]
        if "category" in changes:
            updates["category"] = changes["category"]
        if "expense_date" in changes:
            resolved_today = today if today is not None else self._clock().date()
            updates["expense_date"] = _resolve_expense_date(changes["expense_date"], today=resolved_today)
        if "notes" in changes:
            updates["notes"] = changes["notes"]

        try:
            updated = self._storage.update_by_match(expense_filter, updates=updates)
        except ExpensePersistenceError as ex:
            error_msg = str(ex)
            if "No expense matched" in error_msg:
                raise ExpenseNotFoundError(
                    "No expense matched the given description."
                ) from ex
            if "match this description" in error_msg and "please specify which one" in error_msg:
                # Need to get candidates for the exception - use find_matches
                candidates = self.find_matches(expense_filter)
                raise ExpenseAmbiguousMatchError(
                    f"{len(candidates)} expenses match this description; "
                    "please specify which one.",
                    candidates=candidates,
                ) from ex
            raise

        return updated

    def delete_by_id(self, expense_id: str) -> Expense:
        """
        Raises:
            ExpenseNotFoundError: If `expense_id` does not exist.
        """

        try:
            existing = self._storage.delete_by_id(expense_id)
        except ExpensePersistenceError as ex:
            raise ExpenseNotFoundError(f"No expense found with id '{expense_id}'.") from ex

        if existing is None:
            raise ExpenseNotFoundError(f"No expense found with id '{expense_id}'.")

        self._event_bus.publish(
            EXPENSE_DELETED_EVENT, ExpenseDeleted(expense_id=expense_id)
        )
        self._logger.info("Deleted expense %s.", expense_id)

        return existing

    def delete_by_match(
        self, expense_filter: ExpenseFilter, *, allow_bulk: bool = False
    ) -> tuple[Expense, ...]:
        """
        Delete every expense matching `expense_filter`.

        Raises:
            ExpenseNotFoundError: If nothing matches.
            ExpenseAmbiguousMatchError:
                If more than one expense matches and `allow_bulk` is
                `False` - deletion never silently removes multiple
                records unless the caller explicitly opts in.
        """

        try:
            deleted = self._storage.delete_by_match(expense_filter, allow_bulk=allow_bulk)
        except ExpensePersistenceError as ex:
            error_msg = str(ex)
            if "No expense matched" in error_msg:
                raise ExpenseNotFoundError(
                    "No expense matched the given description."
                ) from ex
            if "match this description" in error_msg and "please specify which one" in error_msg:
                candidates = self.find_matches(expense_filter)
                raise ExpenseAmbiguousMatchError(
                    f"{len(candidates)} expenses match this description; "
                    "please specify which one, or explicitly confirm bulk "
                    "deletion.",
                    candidates=candidates,
                ) from ex
            raise

        for candidate in deleted:
            self._event_bus.publish(
                EXPENSE_DELETED_EVENT, ExpenseDeleted(expense_id=candidate.id)
            )

        self._logger.info(
            "Deleted %d expense(s) by match (bulk=%s).",
            len(deleted),
            allow_bulk,
        )

        return deleted

    def summarize(
        self,
        expense_filter: ExpenseFilter,
        *,
        label: str,
        largest_count: int | None = None,
    ) -> ExpenseSummary:
        """
        Deterministic total/count/breakdowns for every expense
        matching `expense_filter`.
        """

        resolved_largest_count = (
            largest_count
            if largest_count is not None
            else self._config.default_largest_count
        )

        return ExpenseSummary(
            period_label=label,
            currency=self._config.default_currency,
            total_minor=self._storage.sum_amount_minor(expense_filter),
            count=self._storage.count(expense_filter),
            by_category=self._storage.aggregate_by_category(expense_filter),
            by_item=self._storage.aggregate_by_item(expense_filter),
            by_date=self._storage.aggregate_by_date(expense_filter),
            largest=self._storage.largest(expense_filter, limit=resolved_largest_count),
        )

    def compare(
        self,
        filter_current: ExpenseFilter,
        filter_previous: ExpenseFilter,
        *,
        label_current: str,
        label_previous: str,
    ) -> PeriodComparison:
        """
        Deterministically compare two filtered slices of expenses
        (typically two periods, optionally narrowed to one category).
        """

        current_side = PeriodComparisonSide(
            label=label_current,
            total_minor=self._storage.sum_amount_minor(filter_current),
            count=self._storage.count(filter_current),
        )
        previous_side = PeriodComparisonSide(
            label=label_previous,
            total_minor=self._storage.sum_amount_minor(filter_previous),
            count=self._storage.count(filter_previous),
        )
        breakdown = build_category_breakdown(
            self._storage.aggregate_by_category(filter_current),
            self._storage.aggregate_by_category(filter_previous),
        )

        return compare_totals(current_side, previous_side, category_breakdown=breakdown)
