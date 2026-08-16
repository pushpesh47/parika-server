"""
PARIKA Expense Tool - Manifest

Defines the seven `expense.*` Capabilities and their Tool Affordance
Contracts (the JSON Schema + natural-language guidance a model uses
to call each one - see `docs/architecture/Request_Understanding.md`
section 4.4).

Following the Weather/Currency Tool convention (see those modules'
own `manifest.py` docstrings, and
`docs/development/Tool_Guide.md` section 21, "One Tool per
Capability"), each Capability is registered as its own `Tool`, backed
by its own `ExpenseToolDriver` instance bound to exactly one
`ExpenseOperation` at construction time - `ToolRequest` carries no
capability identifier, so a single multi-capability Tool could not
tell which operation a request targeted.

This module owns Tool creation; `ToolManager` only registers and
stores the `Tool` instances produced here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from parika.core.tool_manager.tool import Tool

from .periods import PeriodKeyword

EXPENSE_TOOL_VERSION = "1.0.0"

_PERIOD_KEYWORDS = tuple(keyword.value for keyword in PeriodKeyword)


class ExpenseOperation(StrEnum):
    """The seven Capabilities the Expense Tool implements."""

    ADD = "add_expense"
    GET = "get_expense"
    LIST = "list_expenses"
    UPDATE = "update_expense"
    REMOVE = "remove_expense"
    SUMMARIZE = "summarize_expenses"
    COMPARE = "compare_periods"


EXPENSE_CAPABILITY_ADD = "expense.add_expense"
EXPENSE_CAPABILITY_GET = "expense.get_expense"
EXPENSE_CAPABILITY_LIST = "expense.list_expenses"
EXPENSE_CAPABILITY_UPDATE = "expense.update_expense"
EXPENSE_CAPABILITY_REMOVE = "expense.remove_expense"
EXPENSE_CAPABILITY_SUMMARIZE = "expense.summarize_expenses"
EXPENSE_CAPABILITY_COMPARE = "expense.compare_periods"

EXPENSE_TOOL_ID_ADD = "tool.expense_add_expense"
EXPENSE_TOOL_ID_GET = "tool.expense_get_expense"
EXPENSE_TOOL_ID_LIST = "tool.expense_list_expenses"
EXPENSE_TOOL_ID_UPDATE = "tool.expense_update_expense"
EXPENSE_TOOL_ID_REMOVE = "tool.expense_remove_expense"
EXPENSE_TOOL_ID_SUMMARIZE = "tool.expense_summarize_expenses"
EXPENSE_TOOL_ID_COMPARE = "tool.expense_compare_periods"

OPERATION_CAPABILITY_ID: Mapping[ExpenseOperation, str] = {
    ExpenseOperation.ADD: EXPENSE_CAPABILITY_ADD,
    ExpenseOperation.GET: EXPENSE_CAPABILITY_GET,
    ExpenseOperation.LIST: EXPENSE_CAPABILITY_LIST,
    ExpenseOperation.UPDATE: EXPENSE_CAPABILITY_UPDATE,
    ExpenseOperation.REMOVE: EXPENSE_CAPABILITY_REMOVE,
    ExpenseOperation.SUMMARIZE: EXPENSE_CAPABILITY_SUMMARIZE,
    ExpenseOperation.COMPARE: EXPENSE_CAPABILITY_COMPARE,
}

OPERATION_TOOL_ID: Mapping[ExpenseOperation, str] = {
    ExpenseOperation.ADD: EXPENSE_TOOL_ID_ADD,
    ExpenseOperation.GET: EXPENSE_TOOL_ID_GET,
    ExpenseOperation.LIST: EXPENSE_TOOL_ID_LIST,
    ExpenseOperation.UPDATE: EXPENSE_TOOL_ID_UPDATE,
    ExpenseOperation.REMOVE: EXPENSE_TOOL_ID_REMOVE,
    ExpenseOperation.SUMMARIZE: EXPENSE_TOOL_ID_SUMMARIZE,
    ExpenseOperation.COMPARE: EXPENSE_TOOL_ID_COMPARE,
}

_FAILURE_SEMANTICS_MISSING_INFO = (
    "If a required field (especially the item/description, or the "
    "amount) is missing from the user's request, ask the user for it "
    "rather than inventing a value or calling this tool with a "
    "placeholder."
)

_FAILURE_SEMANTICS_AMBIGUOUS = (
    "If the result has \"status\": \"ambiguous\", multiple expenses "
    "matched and none were changed/removed - list the candidates for "
    "the user (item, amount, date) and ask which one they mean, or "
    "ask them to confirm bulk deletion. If \"status\": \"not_found\", "
    "say so plainly rather than guessing a record."
)

_FILTER_PARAMETER_PROPERTIES: Mapping[str, Any] = {
    "period": {
        "type": "string",
        "enum": list(_PERIOD_KEYWORDS),
        "description": (
            "A relative period keyword. Use 'custom' with start_date/"
            "end_date for an explicit range."
        ),
    },
    "year": {"type": "integer", "description": "Explicit year for month/half/year-based periods."},
    "month": {"type": "integer", "description": "Explicit month (1-12) for month/half-based periods."},
    "start_date": {"type": "string", "description": "Start date (ISO 'YYYY-MM-DD' or a phrase like '1 August'). Required with period='custom'."},
    "end_date": {"type": "string", "description": "End date (ISO 'YYYY-MM-DD' or a phrase like '7 August'). Required with period='custom'."},
    "category": {"type": "string", "description": "Restrict to this category (case-insensitive), e.g. 'Medicine'."},
    "item": {"type": "string", "description": "Restrict to expenses whose item/description contains this text."},
    "min_amount": {"type": "number", "description": "Only expenses with amount greater than or equal to this."},
    "max_amount": {"type": "number", "description": "Only expenses with amount less than or equal to this."},
}

EXPENSE_TOOL_AFFORDANCES: Mapping[str, Mapping[str, Any]] = {
    EXPENSE_CAPABILITY_ADD: {
        "description": "Add a new personal expense.",
        "purpose": "Records a new expense the user reports having spent money on, e.g. 'add rs 2000 for milk today'.",
        "use_when": "the user reports spending money, or explicitly asks to add/log/record an expense.",
        "avoid_when": "the user is asking a question about past expenses (use list/summarize instead) or wants to change/remove an existing one.",
        "requires": "the amount and the item/description. The date defaults to today when omitted.",
        "result_semantics": "Returns the stored expense, including its id. Confirm the amount, item, category (if inferred), and date back to the user naturally.",
        "failure_semantics": _FAILURE_SEMANTICS_MISSING_INFO,
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "The amount spent, e.g. 2000."},
                "item": {"type": "string", "description": "What the expense was for, e.g. 'milk'. Always preserved verbatim."},
                "currency": {"type": "string", "description": "3-letter ISO 4217 currency code. Defaults to the configured default (INR) when omitted."},
                "category": {"type": "string", "description": "A category such as Food, Groceries, Medicine, Transport, Shopping, Bills, Education, Investment, Personal, Household, or Other. Only set this when reasonably confident; omit it rather than guessing."},
                "date": {"type": "string", "description": "When the expense occurred, e.g. 'today', 'yesterday', '5 August', '05/08/2026', or '2026-08-05'. Defaults to today when omitted."},
                "notes": {"type": "string", "description": "Optional free-form note."},
            },
            "required": ["amount", "item"],
        },
    },
    EXPENSE_CAPABILITY_GET: {
        "description": "Retrieve one specific expense by its id.",
        "purpose": "Fetches the full detail of one already-identified expense, e.g. after list_expenses returned candidates.",
        "use_when": "you already have a specific expense_id (from an earlier list/search/ambiguous result) and need its full detail.",
        "avoid_when": "you do not yet have an expense_id - use list_expenses to find it first.",
        "requires": "expense_id.",
        "result_semantics": "Returns the full expense record.",
        "failure_semantics": "If the id does not exist, say the expense could not be found.",
        "parameters": {
            "type": "object",
            "properties": {
                "expense_id": {"type": "string", "description": "The expense's id."},
            },
            "required": ["expense_id"],
        },
    },
    EXPENSE_CAPABILITY_LIST: {
        "description": "List/search personal expenses, optionally filtered by date/period, category, item text, or amount range.",
        "purpose": "Answers 'show my expenses...' / 'show <category> expenses' / 'show expenses above/between...' requests, and locates a specific expense's id before an update/delete.",
        "use_when": "the user wants to see individual expense records, or you need to find the id of a specific expense to reference next.",
        "avoid_when": "the user only wants a total or breakdown, not individual records - use summarize_expenses instead.",
        "requires": "nothing; an empty filter lists every expense (most recent first).",
        "result_semantics": "Returns a list of expenses (most recent first) and the count returned. Summarize naturally; do not dump raw JSON at the user.",
        "failure_semantics": "An empty list simply means nothing matched; say so plainly.",
        "parameters": {
            "type": "object",
            "properties": {
                **_FILTER_PARAMETER_PROPERTIES,
                "limit": {"type": "integer", "description": "Maximum number of results (default 50, capped at 200)."},
                "offset": {"type": "integer", "description": "Number of results to skip, for pagination."},
            },
        },
    },
    EXPENSE_CAPABILITY_UPDATE: {
        "description": "Update an existing expense's amount, item, category, date, currency, or notes.",
        "purpose": "Handles requests like 'change today's milk expense to 1800' or 'change medicine expense from 1200 to 1000'.",
        "use_when": "the user wants to correct or change an already-recorded expense.",
        "avoid_when": "the user wants to add a brand-new expense (use add_expense) or remove one (use remove_expense).",
        "requires": (
            "either expense_id (if already known), or enough filter fields "
            "(date/period, item, category, amount range) to uniquely identify "
            "one expense - plus at least one new value (amount/item/category/"
            "date/currency/notes) to change."
        ),
        "result_semantics": (
            "On success, returns the updated expense. " + _FAILURE_SEMANTICS_AMBIGUOUS
        ),
        "failure_semantics": _FAILURE_SEMANTICS_AMBIGUOUS,
        "parameters": {
            "type": "object",
            "properties": {
                "expense_id": {"type": "string", "description": "The expense's id, if already known."},
                **_FILTER_PARAMETER_PROPERTIES,
                "amount": {"type": "number", "description": "New amount."},
                "item": {"type": "string", "description": "New item/description."},
                "category": {"type": "string", "description": "New category, or an empty string to clear it."},
                "currency": {"type": "string", "description": "New 3-letter currency code."},
                "date": {"type": "string", "description": "New expense date, e.g. 'today', '2026-08-05'."},
                "notes": {"type": "string", "description": "New notes, or an empty string to clear them."},
            },
        },
    },
    EXPENSE_CAPABILITY_REMOVE: {
        "description": "Remove/delete an existing expense.",
        "purpose": "Handles requests like 'remove today's milk expense' or 'delete the 2000 milk expense'.",
        "use_when": "the user wants to delete an already-recorded expense.",
        "avoid_when": "the user wants to change a value instead of deleting the record - use update_expense.",
        "requires": (
            "either expense_id (if already known), or enough filter fields "
            "to uniquely identify one expense. Set confirm_bulk_delete=true "
            "only when the user explicitly asked to remove more than one "
            "matching expense at once."
        ),
        "result_semantics": (
            "On success, returns the removed expense(s). " + _FAILURE_SEMANTICS_AMBIGUOUS
        ),
        "failure_semantics": _FAILURE_SEMANTICS_AMBIGUOUS,
        "parameters": {
            "type": "object",
            "properties": {
                "expense_id": {"type": "string", "description": "The expense's id, if already known."},
                **_FILTER_PARAMETER_PROPERTIES,
                "confirm_bulk_delete": {
                    "type": "boolean",
                    "description": "Set true only when the user explicitly asked to delete every matching expense, not just one.",
                },
            },
        },
    },
    EXPENSE_CAPABILITY_SUMMARIZE: {
        "description": "Compute a deterministic total, count, and category/item/date breakdown for expenses matching a filter.",
        "purpose": "Answers 'how much did I spend...' / 'what did I spend most on...' / 'show my biggest expenses...' requests with exact, calculated figures.",
        "use_when": "the user wants a total, a breakdown by category/item/date, or the largest expenses in a period - never estimate this total yourself.",
        "avoid_when": "the user wants to see individual expense records rather than a total/breakdown - use list_expenses.",
        "requires": "nothing; an empty filter summarizes every expense ever recorded.",
        "result_semantics": "Returns an exact total, count, category/item/date breakdowns, and the largest expenses in the filter. State the total and any breakdown naturally; never recompute or round it yourself.",
        "failure_semantics": "A zero total/count simply means nothing matched; say so plainly.",
        "parameters": {
            "type": "object",
            "properties": {
                **_FILTER_PARAMETER_PROPERTIES,
                "largest_count": {"type": "integer", "description": "How many of the largest expenses to include (default 5)."},
            },
        },
    },
    EXPENSE_CAPABILITY_COMPARE: {
        "description": "Deterministically compare total spending between two periods (optionally restricted to one category).",
        "purpose": "Answers 'compare this month with last month', 'compare August with July', or 'compare first half and second half of August'.",
        "use_when": "the user wants to compare spending between two time periods.",
        "avoid_when": "only one period's total is being asked about - use summarize_expenses.",
        "requires": "period_a and period_b, each shaped like the summarize/list filter (period keyword, or start_date/end_date for a custom range).",
        "result_semantics": "Returns each period's total/count, the exact difference, the percentage change (or an explicit note when the comparison period was zero), the direction (increased/decreased/unchanged), and a per-category breakdown. State these naturally; never recompute the percentage yourself.",
        "failure_semantics": "If either period cannot be resolved, ask the user to clarify which dates/period they mean.",
        "parameters": {
            "type": "object",
            "properties": {
                "period_a": {
                    "type": "object",
                    "description": "The first ('current') period to compare.",
                    "properties": _FILTER_PARAMETER_PROPERTIES,
                },
                "period_b": {
                    "type": "object",
                    "description": "The second ('previous'/comparison) period.",
                    "properties": _FILTER_PARAMETER_PROPERTIES,
                },
                "category": {"type": "string", "description": "Optionally restrict the comparison to one category, e.g. 'Groceries'."},
            },
            "required": ["period_a", "period_b"],
        },
    },
}
"""
Tool Affordance Contracts, registered as each Capability's
`CapabilityDefinition.metadata["tool_affordance"]` (see
`parika/modules/expense/driver.py`).
"""


_TOOL_NAMES: Mapping[ExpenseOperation, str] = {
    ExpenseOperation.ADD: "Expense Add",
    ExpenseOperation.GET: "Expense Get",
    ExpenseOperation.LIST: "Expense List",
    ExpenseOperation.UPDATE: "Expense Update",
    ExpenseOperation.REMOVE: "Expense Remove",
    ExpenseOperation.SUMMARIZE: "Expense Summarize",
    ExpenseOperation.COMPARE: "Expense Compare Periods",
}


def create_expense_tool(operation: ExpenseOperation) -> Tool:
    """
    Build the immutable Tool descriptor for one Expense Capability.
    """

    capability_id = OPERATION_CAPABILITY_ID[operation]
    tool_id = OPERATION_TOOL_ID[operation]
    description = EXPENSE_TOOL_AFFORDANCES[capability_id]["description"]

    return Tool(
        id=tool_id,
        name=_TOOL_NAMES[operation],
        version=EXPENSE_TOOL_VERSION,
        description=description,
        capabilities=(capability_id,),
    )
