"""
PARIKA Expense Storage - PostgreSQL Implementation

PostgreSQL persistence for Expense records.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path, PurePath
from types import MappingProxyType

import psycopg
from psycopg.rows import dict_row

from .exceptions import ExpensePersistenceError
from .filters import ExpenseFilter
from .model import Expense


def _build_where_postgres(expense_filter: ExpenseFilter) -> tuple[str, tuple[object, ...]]:
    """PostgreSQL version of _build_where using %s placeholders."""
    clauses: list[str] = ["1 = 1"]
    params: list[object] = []

    if expense_filter.period is not None:
        clauses.append("expense_date >= %s AND expense_date <= %s")
        params.append(expense_filter.period.start.isoformat())
        params.append(expense_filter.period.end.isoformat())

    if expense_filter.category is not None:
        clauses.append("LOWER(category) = LOWER(%s)")
        params.append(expense_filter.category)

    if expense_filter.item_contains is not None:
        clauses.append("LOWER(item) LIKE %s")
        params.append(f"%{expense_filter.item_contains.lower()}%")

    if expense_filter.min_amount_minor is not None:
        clauses.append("amount_minor >= %s")
        params.append(expense_filter.min_amount_minor)

    if expense_filter.max_amount_minor is not None:
        clauses.append("amount_minor <= %s")
        params.append(expense_filter.max_amount_minor)

    return " AND ".join(clauses), tuple(params)


_COLUMNS: str = (
    "expense_id, amount_minor, currency, item, category, expense_date, "
    "notes, created_at, updated_at"
)

_UNCATEGORIZED_LABEL = "Uncategorized"


def _serialize(expense: Expense) -> tuple:
    return (
        expense.id,
        expense.amount_minor,
        expense.currency,
        expense.item,
        expense.category,
        expense.expense_date.isoformat(),
        expense.notes,
        expense.created_at.isoformat(),
        expense.updated_at.isoformat(),
    )


def _deserialize(row) -> Expense:
    expense_date = row["expense_date"]
    if isinstance(expense_date, str):
        expense_date = date.fromisoformat(expense_date)

    created_at = row["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)

    updated_at = row["updated_at"]
    if isinstance(updated_at, str):
        updated_at = datetime.fromisoformat(updated_at)

    return Expense(
        id=row["expense_id"],
        amount_minor=row["amount_minor"],
        currency=row["currency"],
        item=row["item"],
        category=row["category"],
        expense_date=expense_date,
        notes=row["notes"],
        created_at=created_at,
        updated_at=updated_at,
    )


class PostgreSQLExpenseStorage:
    """PostgreSQL persistence for `Expense` records."""

    __slots__ = ("_pool",)

    def __init__(self, pool) -> None:
        self._pool = pool

    def initialize(self) -> None:
        """No-op: schema is managed by Alembic migrations."""
        pass

    def shutdown(self) -> None:
        """No-op: pool is managed by PoolManager."""
        pass

    def _require_connection(self):
        return self._pool.connection()

    def insert(self, expense: Expense) -> Expense:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        f"INSERT INTO core.expense ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        _serialize(expense),
                    )
                    conn.commit()
                    return expense
                except psycopg.Error as ex:
                    conn.rollback()
                    raise ExpensePersistenceError("Failed to insert expense.") from ex

    def update(self, expense: Expense) -> Expense:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "UPDATE core.expense SET amount_minor = %s, currency = %s, "
                        "item = %s, category = %s, expense_date = %s, notes = %s, "
                        "created_at = %s, updated_at = %s WHERE expense_id = %s;",
                        (*_serialize(expense)[1:], expense.id),
                    )
                    conn.commit()

                    if cur.rowcount == 0:
                        raise ExpensePersistenceError(
                            f"Cannot update unknown expense '{expense.id}'."
                        )

                    return expense

                except psycopg.Error as ex:
                    conn.rollback()
                    raise ExpensePersistenceError("Failed to update expense.") from ex

    def delete(self, expense_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "DELETE FROM core.expense WHERE expense_id = %s;", (expense_id,)
                    )
                    conn.commit()
                    return cur.rowcount > 0

                except psycopg.Error as ex:
                    conn.rollback()
                    raise ExpensePersistenceError("Failed to delete expense.") from ex

    def get(self, expense_id: str) -> Expense | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE expense_id = %s;",
                        (expense_id,),
                    )
                    row = cur.fetchone()

                    return _deserialize(row) if row is not None else None

                except psycopg.Error as ex:
                    raise ExpensePersistenceError("Failed to retrieve expense.") from ex

    def find(
        self, expense_filter: ExpenseFilter, *, limit: int, offset: int = 0
    ) -> tuple[Expense, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                where_sql, params = _build_where_postgres(expense_filter)

                try:
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE {where_sql} "
                        "ORDER BY expense_date DESC, created_at DESC LIMIT %s OFFSET %s;",
                        (*params, limit, offset),
                    )
                    return tuple(_deserialize(row) for row in cur.fetchall())

                except psycopg.Error as ex:
                    raise ExpensePersistenceError("Failed to list expenses.") from ex

    def count(self, expense_filter: ExpenseFilter) -> int:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                where_sql, params = _build_where_postgres(expense_filter)

                try:
                    cur.execute(
                        f"SELECT COUNT(*) FROM core.expense WHERE {where_sql};", params
                    )
                    return int(cur.fetchone()[0])

                except psycopg.Error as ex:
                    raise ExpensePersistenceError("Failed to count expenses.") from ex

    def sum_amount_minor(self, expense_filter: ExpenseFilter) -> int:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                where_sql, params = _build_where_postgres(expense_filter)

                try:
                    cur.execute(
                        f"SELECT COALESCE(SUM(amount_minor), 0) FROM core.expense "
                        f"WHERE {where_sql};",
                        params,
                    )
                    return int(cur.fetchone()[0])

                except psycopg.Error as ex:
                    raise ExpensePersistenceError("Failed to sum expenses.") from ex

    def aggregate_by_category(
        self, expense_filter: ExpenseFilter
    ) -> dict[str, int]:
        return self._aggregate_by(
            f"COALESCE(category, '{_UNCATEGORIZED_LABEL}')", expense_filter
        )

    def aggregate_by_item(self, expense_filter: ExpenseFilter) -> dict[str, int]:
        return self._aggregate_by("item", expense_filter)

    def aggregate_by_date(self, expense_filter: ExpenseFilter) -> dict[str, int]:
        return self._aggregate_by("expense_date", expense_filter)

    def aggregate_by_month(self, expense_filter: ExpenseFilter) -> dict[str, int]:
        return self._aggregate_by("substr(expense_date, 1, 7)", expense_filter)

    def largest(
        self, expense_filter: ExpenseFilter, *, limit: int
    ) -> tuple[Expense, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                where_sql, params = _build_where_postgres(expense_filter)

                try:
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE {where_sql} "
                        "ORDER BY amount_minor DESC, expense_date DESC LIMIT %s;",
                        (*params, limit),
                    )
                    return tuple(_deserialize(row) for row in cur.fetchall())

                except psycopg.Error as ex:
                    raise ExpensePersistenceError(
                        "Failed to retrieve largest expenses."
                    ) from ex

    def _aggregate_by(
        self, group_expression: str, expense_filter: ExpenseFilter
    ) -> dict[str, int]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                where_sql, params = _build_where_postgres(expense_filter)

                try:
                    cur.execute(
                        f"SELECT {group_expression} AS bucket, "
                        "SUM(amount_minor) AS total FROM core.expense "
                        f"WHERE {where_sql} GROUP BY bucket ORDER BY total DESC;",
                        params,
                    )
                    return {row["bucket"]: int(row["total"]) for row in cur.fetchall()}

                except psycopg.Error as ex:
                    raise ExpensePersistenceError("Failed to aggregate expenses.") from ex

    def update_by_id(
        self, expense_id: str, *, updates: dict[str, object]
    ) -> Expense:
        """
        Atomically update an expense by id within a single transaction.

        Args:
            expense_id: The expense id to update.
            updates: Dictionary of field updates (amount_minor, currency, item,
                category, expense_date, notes).

        Returns:
            The updated Expense.

        Raises:
            ExpensePersistenceError: If the expense does not exist or update fails.
        """
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    conn.execute("BEGIN;")

                    # Get existing expense
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE expense_id = %s;",
                        (expense_id,),
                    )
                    row = cur.fetchone()

                    if row is None:
                        conn.rollback()
                        raise ExpensePersistenceError(
                            f"Cannot update unknown expense '{expense_id}'."
                        )

                    expense = _deserialize(row)

                    # Apply updates
                    new_amount_minor = updates.get("amount_minor", expense.amount_minor)
                    new_currency = updates.get("currency", expense.currency)
                    new_item = updates.get("item", expense.item)
                    new_category = updates.get("category", expense.category)
                    new_expense_date = updates.get("expense_date", expense.expense_date)
                    new_notes = updates.get("notes", expense.notes)

                    # Update in database
                    cur.execute(
                        "UPDATE core.expense SET amount_minor = %s, currency = %s, "
                        "item = %s, category = %s, expense_date = %s, notes = %s, "
                        "updated_at = %s WHERE expense_id = %s;",
                        (
                            new_amount_minor,
                            new_currency,
                            new_item,
                            new_category,
                            new_expense_date.isoformat() if isinstance(new_expense_date, date) else new_expense_date,
                            new_notes,
                            datetime.now(UTC).isoformat(),
                            expense_id,
                        ),
                    )

                    if cur.rowcount == 0:
                        conn.rollback()
                        raise ExpensePersistenceError(
                            f"Cannot update unknown expense '{expense_id}'."
                        )

                    conn.commit()

                    return Expense(
                        id=expense.id,
                        amount_minor=new_amount_minor,
                        currency=new_currency,
                        item=new_item,
                        category=new_category,
                        expense_date=new_expense_date,
                        notes=new_notes,
                        created_at=expense.created_at,
                        updated_at=datetime.now(UTC),
                    )

                except psycopg.Error as ex:
                    conn.rollback()
                    raise ExpensePersistenceError("Failed to update expense by id.") from ex

    def delete_by_id(self, expense_id: str) -> Expense | None:
        """
        Atomically delete an expense by id within a single transaction.

        Returns the deleted expense if it existed, None otherwise.
        """
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    conn.execute("BEGIN;")

                    # Get existing expense before deletion
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE expense_id = %s;",
                        (expense_id,),
                    )
                    row = cur.fetchone()

                    if row is None:
                        conn.rollback()
                        return None

                    expense = _deserialize(row)

                    # Delete the expense
                    cur.execute(
                        "DELETE FROM core.expense WHERE expense_id = %s;", (expense_id,)
                    )

                    if cur.rowcount == 0:
                        conn.rollback()
                        return None

                    conn.commit()
                    return expense

                except psycopg.Error as ex:
                    conn.rollback()
                    raise ExpensePersistenceError("Failed to delete expense by id.") from ex

    def update_by_match(
        self, expense_filter: ExpenseFilter, *, updates: dict[str, object]
    ) -> Expense:
        """
        Atomically find and update a single expense matching the filter.

        Raises:
            ExpensePersistenceError: If zero or multiple expenses match.
        """
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    conn.execute("BEGIN;")

                    where_sql, params = _build_where_postgres(expense_filter)

                    # Find matching expenses
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE {where_sql} "
                        "ORDER BY expense_date DESC, created_at DESC;",
                        params,
                    )
                    rows = cur.fetchall()

                    if not rows:
                        conn.rollback()
                        raise ExpensePersistenceError(
                            "No expense matched the given description."
                        )

                    if len(rows) > 1:
                        conn.rollback()
                        raise ExpensePersistenceError(
                            f"{len(rows)} expenses match this description; "
                            "please specify which one."
                        )

                    expense = _deserialize(rows[0])

                    # Apply updates
                    new_amount_minor = updates.get("amount_minor", expense.amount_minor)
                    new_currency = updates.get("currency", expense.currency)
                    new_item = updates.get("item", expense.item)
                    new_category = updates.get("category", expense.category)
                    new_expense_date = updates.get("expense_date", expense.expense_date)
                    new_notes = updates.get("notes", expense.notes)

                    # Update in database
                    cur.execute(
                        "UPDATE core.expense SET amount_minor = %s, currency = %s, "
                        "item = %s, category = %s, expense_date = %s, notes = %s, "
                        "updated_at = %s WHERE expense_id = %s;",
                        (
                            new_amount_minor,
                            new_currency,
                            new_item,
                            new_category,
                            new_expense_date.isoformat() if isinstance(new_expense_date, date) else new_expense_date,
                            new_notes,
                            datetime.now(UTC).isoformat(),
                            expense.id,
                        ),
                    )

                    if cur.rowcount == 0:
                        conn.rollback()
                        raise ExpensePersistenceError(
                            f"Cannot update unknown expense '{expense.id}'."
                        )

                    conn.commit()

                    return Expense(
                        id=expense.id,
                        amount_minor=new_amount_minor,
                        currency=new_currency,
                        item=new_item,
                        category=new_category,
                        expense_date=new_expense_date,
                        notes=new_notes,
                        created_at=expense.created_at,
                        updated_at=datetime.now(UTC),
                    )

                except psycopg.Error as ex:
                    conn.rollback()
                    raise ExpensePersistenceError("Failed to update expense by match.") from ex

    def delete_by_match(
        self, expense_filter: ExpenseFilter, *, allow_bulk: bool = False
    ) -> tuple[Expense, ...]:
        """
        Atomically find and delete expenses matching the filter.

        Args:
            expense_filter: Filter to match expenses.
            allow_bulk: If False, raises when multiple matches found.

        Returns:
            Tuple of deleted expenses.

        Raises:
            ExpensePersistenceError: If zero matches, or multiple matches with allow_bulk=False.
        """
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    conn.execute("BEGIN;")

                    where_sql, params = _build_where_postgres(expense_filter)

                    # Find matching expenses
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE {where_sql} "
                        "ORDER BY expense_date DESC, created_at DESC;",
                        params,
                    )
                    rows = cur.fetchall()

                    if not rows:
                        conn.rollback()
                        raise ExpensePersistenceError(
                            "No expense matched the given description."
                        )

                    if len(rows) > 1 and not allow_bulk:
                        conn.rollback()
                        raise ExpensePersistenceError(
                            f"{len(rows)} expenses match this description; "
                            "please specify which one, or explicitly confirm bulk "
                            "deletion."
                        )

                    deleted = []
                    for row in rows:
                        expense = _deserialize(row)
                        cur.execute(
                            "DELETE FROM core.expense WHERE expense_id = %s;", (expense.id,)
                        )
                        if cur.rowcount > 0:
                            deleted.append(expense)

                    conn.commit()
                    return tuple(deleted)

                except psycopg.Error as ex:
                    conn.rollback()
                    raise ExpensePersistenceError("Failed to delete expense by match.") from ex
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "UPDATE core.expense SET amount_minor = %s, currency = %s, "
                        "item = %s, category = %s, expense_date = %s, notes = %s, "
                        "created_at = %s, updated_at = %s WHERE expense_id = %s",
                        (*_serialize(expense)[1:], expense.id),
                    )
                    conn.commit()

                    if cur.rowcount == 0:
                        raise ExpensePersistenceError(
                            f"Cannot update unknown expense '{expense.id}'."
                        )
                    return expense
                except psycopg.Error as ex:
                    conn.rollback()
                    raise ExpensePersistenceError("Failed to update expense.") from ex

    def delete(self, expense_id: str) -> Expense | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    # First get the expense
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE expense_id = %s",
                        (expense_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None
                    
                    expense = _deserialize(row)
                    
                    # Then delete it
                    cur.execute("DELETE FROM core.expense WHERE expense_id = %s", (expense_id,))
                    conn.commit()
                    return expense
                except psycopg.Error as ex:
                    conn.rollback()
                    raise ExpensePersistenceError("Failed to delete expense.") from ex

    def get(self, expense_id: str) -> Expense | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE expense_id = %s",
                        (expense_id,),
                    )
                    row = cur.fetchone()
                    return _deserialize(row) if row else None
                except psycopg.Error as ex:
                    raise ExpensePersistenceError("Failed to retrieve expense.") from ex

    def find(
        self, expense_filter: ExpenseFilter, *, limit: int, offset: int = 0
    ) -> tuple[Expense, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                where_sql, params = _build_where_postgres(expense_filter)
                try:
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE {where_sql} "
                        "ORDER BY expense_date DESC, created_at DESC LIMIT %s OFFSET %s",
                        (*params, limit, offset),
                    )
                    return tuple(_deserialize(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise ExpensePersistenceError("Failed to list expenses.") from ex

    def count(self, expense_filter: ExpenseFilter) -> int:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                where_sql, params = _build_where_postgres(expense_filter)
                try:
                    cur.execute(f"SELECT COUNT(*) FROM core.expense WHERE {where_sql}", params)
                    return int(cur.fetchone()[0])
                except psycopg.Error as ex:
                    raise ExpensePersistenceError("Failed to count expenses.") from ex

    def sum_amount_minor(self, expense_filter: ExpenseFilter) -> int:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                where_sql, params = _build_where_postgres(expense_filter)
                try:
                    cur.execute(
                        f"SELECT COALESCE(SUM(amount_minor), 0) FROM core.expense WHERE {where_sql}",
                        params,
                    )
                    return int(cur.fetchone()[0])
                except psycopg.Error as ex:
                    raise ExpensePersistenceError("Failed to sum expenses.") from ex

    def aggregate_by_category(self, expense_filter: ExpenseFilter) -> dict[str, int]:
        return self._aggregate_by(
            f"COALESCE(category, '{_UNCATEGORIZED_LABEL}')", expense_filter
        )

    def aggregate_by_item(self, expense_filter: ExpenseFilter) -> dict[str, int]:
        return self._aggregate_by("item", expense_filter)

    def aggregate_by_date(self, expense_filter: ExpenseFilter) -> dict[str, int]:
        return self._aggregate_by("expense_date", expense_filter)

    def aggregate_by_month(self, expense_filter: ExpenseFilter) -> dict[str, int]:
        return self._aggregate_by("to_char(expense_date, 'YYYY-MM')", expense_filter)

    def largest(
        self, expense_filter: ExpenseFilter, *, limit: int
    ) -> tuple[Expense, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                where_sql, params = _build_where_postgres(expense_filter)
                try:
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE {where_sql} "
                        "ORDER BY amount_minor DESC, expense_date DESC LIMIT %s",
                        (*params, limit),
                    )
                    return tuple(_deserialize(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise ExpensePersistenceError("Failed to retrieve largest expenses.") from ex

    def _aggregate_by(
        self, group_expression: str, expense_filter: ExpenseFilter
    ) -> dict[str, int]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                where_sql, params = _build_where_postgres(expense_filter)
                try:
                    cur.execute(
                        f"SELECT {group_expression} AS bucket, "
                        "SUM(amount_minor) AS total FROM core.expense "
                        f"WHERE {where_sql} GROUP BY bucket ORDER BY total DESC",
                        params,
                    )
                    result = {}
                    for row in cur.fetchall():
                        bucket = row[0]
                        # Convert date/datetime objects to ISO format strings for JSON serialization
                        if hasattr(bucket, 'isoformat'):
                            bucket = bucket.isoformat()
                        result[str(bucket)] = int(row[1])
                    return result
                except psycopg.Error as ex:
                    raise ExpensePersistenceError("Failed to aggregate expenses.") from ex

    def update_by_id(
        self, expense_id: str, *, updates: dict[str, object]
    ) -> Expense:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute("BEGIN")
                    # Get existing expense
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE expense_id = %s",
                        (expense_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        cur.execute("ROLLBACK")
                        raise ExpensePersistenceError(
                            f"Cannot update unknown expense '{expense_id}'."
                        )

                    expense = _deserialize(row)

                    # Apply updates
                    new_amount_minor = updates.get("amount_minor", expense.amount_minor)
                    new_currency = updates.get("currency", expense.currency)
                    new_item = updates.get("item", expense.item)
                    new_category = updates.get("category", expense.category)
                    new_expense_date = updates.get("expense_date", expense.expense_date)
                    new_notes = updates.get("notes", expense.notes)

                    # Update in database
                    cur.execute(
                        "UPDATE core.expense SET amount_minor = %s, currency = %s, "
                        "item = %s, category = %s, expense_date = %s, notes = %s, "
                        "updated_at = %s WHERE expense_id = %s",
                        (
                            new_amount_minor,
                            new_currency,
                            new_item,
                            new_category,
                            new_expense_date.isoformat() if isinstance(new_expense_date, date) else new_expense_date,
                            new_notes,
                            datetime.now(UTC).isoformat(),
                            expense_id,
                        ),
                    )

                    if cur.rowcount == 0:
                        cur.execute("ROLLBACK")
                        raise ExpensePersistenceError(
                            f"Cannot update unknown expense '{expense_id}'."
                        )

                    cur.execute("COMMIT")

                    return Expense(
                        id=expense.id,
                        amount_minor=new_amount_minor,
                        currency=new_currency,
                        item=new_item,
                        category=new_category,
                        expense_date=new_expense_date,
                        notes=new_notes,
                        created_at=expense.created_at,
                        updated_at=datetime.now(UTC),
                    )
                except psycopg.Error as ex:
                    cur.execute("ROLLBACK")
                    raise ExpensePersistenceError("Failed to update expense by id.") from ex

    def delete_by_id(self, expense_id: str) -> Expense | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute("BEGIN")
                    # Get existing expense before deletion
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE expense_id = %s",
                        (expense_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        cur.execute("ROLLBACK")
                        return None

                    expense = _deserialize(row)

                    # Delete the expense
                    cur.execute("DELETE FROM core.expense WHERE expense_id = %s", (expense_id,))

                    if cur.rowcount == 0:
                        cur.execute("ROLLBACK")
                        return None

                    cur.execute("COMMIT")
                    return expense
                except psycopg.Error as ex:
                    cur.execute("ROLLBACK")
                    raise ExpensePersistenceError("Failed to delete expense by id.") from ex

    def update_by_match(
        self, expense_filter: ExpenseFilter, *, updates: dict[str, object]
    ) -> Expense:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute("BEGIN")
                    where_sql, params = _build_where_postgres(expense_filter)

                    # Find matching expenses
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE {where_sql} "
                        "ORDER BY expense_date DESC, created_at DESC",
                        params,
                    )
                    rows = cur.fetchall()

                    if not rows:
                        cur.execute("ROLLBACK")
                        raise ExpensePersistenceError(
                            "No expense matched the given description."
                        )

                    if len(rows) > 1:
                        cur.execute("ROLLBACK")
                        raise ExpensePersistenceError(
                            f"{len(rows)} expenses match this description; "
                            "please specify which one."
                        )

                    expense = _deserialize(rows[0])

                    # Apply updates
                    new_amount_minor = updates.get("amount_minor", expense.amount_minor)
                    new_currency = updates.get("currency", expense.currency)
                    new_item = updates.get("item", expense.item)
                    new_category = updates.get("category", expense.category)
                    new_expense_date = updates.get("expense_date", expense.expense_date)
                    new_notes = updates.get("notes", expense.notes)

                    # Update in database
                    cur.execute(
                        "UPDATE core.expense SET amount_minor = %s, currency = %s, "
                        "item = %s, category = %s, expense_date = %s, notes = %s, "
                        "updated_at = %s WHERE expense_id = %s",
                        (
                            new_amount_minor,
                            new_currency,
                            new_item,
                            new_category,
                            new_expense_date.isoformat() if isinstance(new_expense_date, date) else new_expense_date,
                            new_notes,
                            datetime.now(UTC).isoformat(),
                            expense.id,
                        ),
                    )

                    if cur.rowcount == 0:
                        cur.execute("ROLLBACK")
                        raise ExpensePersistenceError(
                            f"Cannot update unknown expense '{expense.id}'."
                        )

                    cur.execute("COMMIT")

                    return Expense(
                        id=expense.id,
                        amount_minor=new_amount_minor,
                        currency=new_currency,
                        item=new_item,
                        category=new_category,
                        expense_date=new_expense_date,
                        notes=new_notes,
                        created_at=expense.created_at,
                        updated_at=datetime.now(UTC),
                    )
                except psycopg.Error as ex:
                    cur.execute("ROLLBACK")
                    raise ExpensePersistenceError("Failed to update expense by match.") from ex

    def delete_by_match(
        self, expense_filter: ExpenseFilter, *, allow_bulk: bool = False
    ) -> tuple[Expense, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute("BEGIN")
                    where_sql, params = _build_where_postgres(expense_filter)

                    # Find matching expenses
                    cur.execute(
                        f"SELECT {_COLUMNS} FROM core.expense WHERE {where_sql} "
                        "ORDER BY expense_date DESC, created_at DESC",
                        params,
                    )
                    rows = cur.fetchall()

                    if not rows:
                        cur.execute("ROLLBACK")
                        raise ExpensePersistenceError(
                            "No expense matched the given description."
                        )

                    if len(rows) > 1 and not allow_bulk:
                        cur.execute("ROLLBACK")
                        raise ExpensePersistenceError(
                            f"{len(rows)} expenses match this description; "
                            "please specify which one, or explicitly confirm bulk "
                            "deletion."
                        )

                    deleted = []
                    for row in rows:
                        expense = _deserialize(row)
                        cur.execute("DELETE FROM core.expense WHERE expense_id = %s", (expense.id,))
                        if cur.rowcount > 0:
                            deleted.append(expense)

                    cur.execute("COMMIT")
                    return tuple(deleted)
                except psycopg.Error as ex:
                    cur.execute("ROLLBACK")
                    raise ExpensePersistenceError("Failed to delete expense by match.") from ex


# Reuse the helper functions from the SQLite storage
# (imported at the top of the file)
# from .storage import _build_where_postgres, _serialize, _deserialize