"""
PARIKA Expense Tool - Driver

Implements the `ToolDriver` contract for all seven `expense.*`
Capabilities.

A single `ExpenseToolDriver` instance is bound to exactly one
`ExpenseOperation` at construction time (see `manifest.py`'s module
docstring). `ExpenseModuleDriver` constructs seven instances - one
per Capability - all sharing the same `ExpenseService`, and registers
each as its own Tool.

This driver is intentionally thin: it only translates
`ToolRequest.arguments` (whatever shape a model's native tool call
produced) into `ExpenseService` calls and translates the result back
into a plain, JSON-serializable `ToolResponse.result`. Every actual
business rule (validation, ambiguity handling, date/period
resolution, calculation) lives in `service.py`/`dates.py`/
`periods.py`/`calculations.py` - never here, and never in a second
reasoning path (see this package's own module docstring).

Ambiguous/not-found match-based update/delete outcomes are
deliberately *not* re-raised as Tool execution failures: they are a
normal, useful result (`{"status": "ambiguous", "candidates": [...]}`
/ `{"status": "not_found", ...}`) the model should relay to the user
for clarification, not an error. `ExpenseNotFoundError` raised for an
*explicit* `expense_id` that does not exist, by contrast, propagates
as a genuine Tool execution error, since the caller claimed to
already know a valid id.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse

from .calculations import ExpenseSummary, PeriodComparison
from .exceptions import (
    ExpenseAmbiguousMatchError,
    ExpenseNotFoundError,
    ExpenseInvalidRequestError,
)
from .filters import ExpenseFilter
from .manifest import ExpenseOperation
from .money import from_minor_units, to_minor_units
from .periods import Period, resolve_period
from .dates import parse_expense_date
from .service import ExpenseService


class ExpenseToolDriver:
    """
    ToolDriver implementing one Expense Tool Capability.
    """

    def __init__(self, operation: ExpenseOperation, *, service: ExpenseService) -> None:
        self._operation = operation
        self._service = service

    def execute(self, request: ToolRequest) -> ToolResponse:
        handler = _HANDLERS[self._operation]
        return handler(self._service, request.arguments)


def _handle_add(service: ExpenseService, arguments: Mapping[str, Any]) -> ToolResponse:
    expense = service.create(
        amount=arguments.get("amount"),
        item=arguments.get("item"),
        currency=arguments.get("currency"),
        category=arguments.get("category"),
        expense_date=arguments.get("date"),
        notes=arguments.get("notes"),
        today=date.today(),
    )
    return ToolResponse(
        result={"status": "success", "expense": expense.to_dict()},
        attributes={"expense_id": expense.id},
    )


def _handle_get(service: ExpenseService, arguments: Mapping[str, Any]) -> ToolResponse:
    expense_id = arguments.get("expense_id")

    if not isinstance(expense_id, str) or not expense_id.strip():
        raise ExpenseInvalidRequestError("expense_id is required.")

    expense = service.get(expense_id.strip())
    return ToolResponse(result={"status": "success", "expense": expense.to_dict()})


def _handle_list(service: ExpenseService, arguments: Mapping[str, Any]) -> ToolResponse:
    today = date.today()
    expense_filter = build_expense_filter(arguments, today=today)

    limit = arguments.get("limit")
    offset = arguments.get("offset", 0)

    expenses = service.list(
        expense_filter,
        limit=int(limit) if limit is not None else None,
        offset=int(offset) if offset is not None else 0,
    )

    return ToolResponse(
        result={
            "status": "success",
            "count": len(expenses),
            "expenses": [expense.to_dict() for expense in expenses],
        }
    )


def _handle_update(service: ExpenseService, arguments: Mapping[str, Any]) -> ToolResponse:
    today = date.today()
    expense_id = arguments.get("expense_id")
    changes = build_update_changes(arguments)

    if isinstance(expense_id, str) and expense_id.strip():
        updated = service.update_by_id(expense_id.strip(), today=today, **changes)
        return ToolResponse(result={"status": "success", "expense": updated.to_dict()})

    expense_filter = build_expense_filter(arguments, today=today)

    try:
        updated = service.update_by_match(expense_filter, changes=changes, today=today)
    except ExpenseAmbiguousMatchError as ex:
        return ToolResponse(result=_ambiguous_result(ex))
    except ExpenseNotFoundError as ex:
        return ToolResponse(result={"status": "not_found", "message": str(ex)})

    return ToolResponse(result={"status": "success", "expense": updated.to_dict()})


def _handle_remove(service: ExpenseService, arguments: Mapping[str, Any]) -> ToolResponse:
    today = date.today()
    expense_id = arguments.get("expense_id")

    if isinstance(expense_id, str) and expense_id.strip():
        removed = service.delete_by_id(expense_id.strip())
        return ToolResponse(result={"status": "success", "removed": [removed.to_dict()]})

    expense_filter = build_expense_filter(arguments, today=today)
    allow_bulk = bool(arguments.get("confirm_bulk_delete", False))

    try:
        removed = service.delete_by_match(expense_filter, allow_bulk=allow_bulk)
    except ExpenseAmbiguousMatchError as ex:
        return ToolResponse(result=_ambiguous_result(ex))
    except ExpenseNotFoundError as ex:
        return ToolResponse(result={"status": "not_found", "message": str(ex)})

    return ToolResponse(
        result={"status": "success", "removed": [expense.to_dict() for expense in removed]}
    )


def _handle_summarize(service: ExpenseService, arguments: Mapping[str, Any]) -> ToolResponse:
    today = date.today()
    expense_filter = build_expense_filter(arguments, today=today)
    label = expense_filter.period.label if expense_filter.period is not None else "all time"

    largest_count = arguments.get("largest_count")
    summary = service.summarize(
        expense_filter,
        label=label,
        largest_count=int(largest_count) if largest_count is not None else None,
    )

    return ToolResponse(result={"status": "success", **_summary_to_dict(summary)})


def _handle_compare(service: ExpenseService, arguments: Mapping[str, Any]) -> ToolResponse:
    today = date.today()

    period_a_args: dict[str, Any] = dict(arguments.get("period_a") or {})
    period_b_args: dict[str, Any] = dict(arguments.get("period_b") or {})
    category = arguments.get("category")

    if isinstance(category, str) and category.strip():
        period_a_args.setdefault("category", category)
        period_b_args.setdefault("category", category)

    filter_a = build_expense_filter(period_a_args, today=today)
    filter_b = build_expense_filter(period_b_args, today=today)

    if filter_a.period is None or filter_b.period is None:
        raise ExpenseInvalidRequestError(
            "compare_periods requires a period (or start_date/end_date) "
            "for both period_a and period_b."
        )

    comparison = service.compare(
        filter_a,
        filter_b,
        label_current=filter_a.period.label,
        label_previous=filter_b.period.label,
    )

    return ToolResponse(result={"status": "success", **_comparison_to_dict(comparison)})


_HANDLERS = {
    ExpenseOperation.ADD: _handle_add,
    ExpenseOperation.GET: _handle_get,
    ExpenseOperation.LIST: _handle_list,
    ExpenseOperation.UPDATE: _handle_update,
    ExpenseOperation.REMOVE: _handle_remove,
    ExpenseOperation.SUMMARIZE: _handle_summarize,
    ExpenseOperation.COMPARE: _handle_compare,
}


def build_update_changes(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """
    Translate a Tool-call-shaped (or API-request-shaped) argument
    mapping into the `**changes` `ExpenseService.update_by_id()`/
    `update_by_match()` expect: `date` -> `expense_date`, `category`/
    `notes` passed through only when the key is *present* (so an
    explicit empty string/`None` clears the field, while an absent
    key leaves it unchanged) - shared by both the Tool-calling path
    here and the direct `PATCH /api/v1/expenses/{id}` API handler
    (`parika/api/handlers/expense.py`), so update semantics never
    diverge between the two entry points.
    """

    changes: dict[str, Any] = {}

    if "amount" in arguments and arguments["amount"] is not None:
        changes["amount"] = arguments["amount"]
    if "currency" in arguments and arguments["currency"] is not None:
        changes["currency"] = arguments["currency"]
    if "item" in arguments and arguments["item"] is not None:
        changes["item"] = arguments["item"]
    if "category" in arguments:
        changes["category"] = arguments["category"]
    if "date" in arguments and arguments["date"] is not None:
        changes["expense_date"] = arguments["date"]
    if "notes" in arguments:
        changes["notes"] = arguments["notes"]

    return changes


def _build_period(arguments: Mapping[str, Any], *, today: date) -> Period | None:
    period_keyword = arguments.get("period")
    start_raw = arguments.get("start_date")
    end_raw = arguments.get("end_date")
    year = arguments.get("year")
    month = arguments.get("month")

    if period_keyword is None and start_raw is None and end_raw is None:
        return None

    if period_keyword is not None and period_keyword != "custom":
        return resolve_period(
            period_keyword,
            today=today,
            year=int(year) if year is not None else None,
            month=int(month) if month is not None else None,
        )

    if start_raw is None or end_raw is None:
        raise ExpenseInvalidRequestError(
            "A custom date range requires both start_date and end_date."
        )

    start_date = parse_expense_date(str(start_raw), today=today)
    end_date = parse_expense_date(str(end_raw), today=today)

    return Period(
        start=start_date,
        end=end_date,
        label=f"{start_date.isoformat()} to {end_date.isoformat()}",
    )


def build_expense_filter(arguments: Mapping[str, Any], *, today: date) -> ExpenseFilter:
    """
    Translate a Tool-call-shaped (or API-request-shaped) argument
    mapping into an `ExpenseFilter`. Shared by the Tool-calling path
    here and the direct `GET /api/v1/expenses`/`.../summary` API
    handlers (`parika/api/handlers/expense.py`), so filter semantics
    never diverge between the two entry points.
    """

    category = arguments.get("category")
    item = arguments.get("item")
    min_amount = arguments.get("min_amount")
    max_amount = arguments.get("max_amount")

    return ExpenseFilter(
        period=_build_period(arguments, today=today),
        category=category.strip() if isinstance(category, str) and category.strip() else None,
        item_contains=item.strip() if isinstance(item, str) and item.strip() else None,
        min_amount_minor=to_minor_units(min_amount) if min_amount is not None else None,
        max_amount_minor=to_minor_units(max_amount) if max_amount is not None else None,
    )


def _ambiguous_result(ex: ExpenseAmbiguousMatchError) -> dict[str, Any]:
    return {
        "status": "ambiguous",
        "message": str(ex),
        "candidates": [candidate.to_dict() for candidate in ex.candidates],
    }


def _summary_to_dict(summary: ExpenseSummary) -> dict[str, Any]:
    return {
        "period_label": summary.period_label,
        "currency": summary.currency,
        "total": str(from_minor_units(summary.total_minor)),
        "count": summary.count,
        "by_category": {
            category: str(from_minor_units(total))
            for category, total in summary.by_category.items()
        },
        "by_item": {
            item: str(from_minor_units(total)) for item, total in summary.by_item.items()
        },
        "by_date": {
            day: str(from_minor_units(total)) for day, total in summary.by_date.items()
        },
        "largest_expenses": [expense.to_dict() for expense in summary.largest],
    }


def _comparison_to_dict(comparison: PeriodComparison) -> dict[str, Any]:
    return {
        "current": {
            "label": comparison.current.label,
            "total": str(from_minor_units(comparison.current.total_minor)),
            "count": comparison.current.count,
        },
        "previous": {
            "label": comparison.previous.label,
            "total": str(from_minor_units(comparison.previous.total_minor)),
            "count": comparison.previous.count,
        },
        "difference": str(from_minor_units(comparison.difference_minor)),
        "percentage_change": comparison.percentage_change,
        "direction": comparison.direction,
        "note": comparison.note,
        "category_breakdown": {
            category: {
                "current": str(from_minor_units(current_minor)),
                "previous": str(from_minor_units(previous_minor)),
                "difference": str(from_minor_units(difference_minor)),
            }
            for category, (
                current_minor,
                previous_minor,
                difference_minor,
            ) in comparison.category_breakdown.items()
        },
    }
