"""
PARIKA Expense Tool - SQLite Storage

Persistence layer for `Expense` records, mirroring
`ExperienceStorage`'s exact schema/pragma/connection-lifecycle
pattern (see `parika/modules/experience/storage.py`) for consistency
with every other PARIKA module that owns its own SQLite database
file - see `docs/architecture/adr/0003-expense-management.md`,
Decision 3 ("reuse the existing per-module SQLite pattern; do not
introduce a new persistence technology").

Every monetary aggregation (`SUM`, category/item/date/month
`GROUP BY`) is performed by SQLite directly over the `amount_minor`
`INTEGER` column - never in Python, and never as floating point. See
`money.py`'s module docstring.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path, PurePath

from .exceptions import ExpensePersistenceError
from .filters import ExpenseFilter
from .model import Expense

SQLITE_SCHEMA_VERSION: int = 1
SQLITE_BUSY_TIMEOUT_MS: int = 5000

_COLUMNS: str = (
    "expense_id, amount_minor, currency, item, category, expense_date, "
    "notes, created_at, updated_at"
)

_UNCATEGORIZED_LABEL = "Uncategorized"


class ExpenseStorage:
    """SQLite persistence for `Expense` records."""

    __slots__ = ("_database_path", "_connection")

    def __init__(self, database_path: Path) -> None:
        if not isinstance(database_path, PurePath):
            raise TypeError("database_path must be a pathlib.Path object.")

        self._database_path: Path = database_path
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        if self._connection is not None:
            return

        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)

            self._connection = sqlite3.connect(database=self._database_path)
            self._connection.row_factory = sqlite3.Row

            self._connection.execute("PRAGMA journal_mode = WAL;")
            self._connection.execute("PRAGMA synchronous = NORMAL;")
            self._connection.execute(
                f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};"
            )

            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS expenses (
                    expense_id TEXT PRIMARY KEY,
                    amount_minor INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    item TEXT NOT NULL,
                    category TEXT NULL,
                    expense_date TEXT NOT NULL,
                    notes TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_expenses_date
                ON expenses(expense_date);

                CREATE INDEX IF NOT EXISTS idx_expenses_category
                ON expenses(category);
                """
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO metadata (key, value) VALUES "
                "('schema_version', ?), ('created_at', ?);",
                (str(SQLITE_SCHEMA_VERSION), datetime.now(UTC).isoformat()),
            )
            self._connection.execute(
                f"PRAGMA user_version = {SQLITE_SCHEMA_VERSION};"
            )
            self._connection.commit()

        except Exception:
            if self._connection is not None:
                try:
                    self._connection.close()
                finally:
                    self._connection = None
            raise

    def shutdown(self) -> None:
        if self._connection is None:
            return

        try:
            self._connection.close()
        except sqlite3.Error as ex:
            raise ExpensePersistenceError(
                "Failed to shut down expense storage."
            ) from ex
        finally:
            self._connection = None

    def insert(self, expense: Expense) -> Expense:
        connection = self._require_connection()

        try:
            connection.execute(
                f"INSERT INTO expenses ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                _serialize(expense),
            )
            connection.commit()
            return expense

        except sqlite3.Error as ex:
            connection.rollback()
            raise ExpensePersistenceError("Failed to insert expense.") from ex

    def update(self, expense: Expense) -> Expense:
        connection = self._require_connection()

        try:
            cursor = connection.execute(
                "UPDATE expenses SET amount_minor = ?, currency = ?, "
                "item = ?, category = ?, expense_date = ?, notes = ?, "
                "created_at = ?, updated_at = ? WHERE expense_id = ?;",
                (*_serialize(expense)[1:], expense.id),
            )
            connection.commit()

            if cursor.rowcount == 0:
                raise ExpensePersistenceError(
                    f"Cannot update unknown expense '{expense.id}'."
                )

            return expense

        except sqlite3.Error as ex:
            connection.rollback()
            raise ExpensePersistenceError("Failed to update expense.") from ex

    def delete(self, expense_id: str) -> bool:
        connection = self._require_connection()

        try:
            cursor = connection.execute(
                "DELETE FROM expenses WHERE expense_id = ?;", (expense_id,)
            )
            connection.commit()
            return cursor.rowcount > 0

        except sqlite3.Error as ex:
            connection.rollback()
            raise ExpensePersistenceError("Failed to delete expense.") from ex

    def get(self, expense_id: str) -> Expense | None:
        connection = self._require_connection()

        try:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM expenses WHERE expense_id = ?;",
                (expense_id,),
            ).fetchone()

            return _deserialize(row) if row is not None else None

        except sqlite3.Error as ex:
            raise ExpensePersistenceError("Failed to retrieve expense.") from ex

    def find(
        self, expense_filter: ExpenseFilter, *, limit: int, offset: int = 0
    ) -> tuple[Expense, ...]:
        connection = self._require_connection()
        where_sql, params = _build_where(expense_filter)

        try:
            cursor = connection.execute(
                f"SELECT {_COLUMNS} FROM expenses WHERE {where_sql} "
                "ORDER BY expense_date DESC, created_at DESC LIMIT ? OFFSET ?;",
                (*params, limit, offset),
            )
            return tuple(_deserialize(row) for row in cursor.fetchall())

        except sqlite3.Error as ex:
            raise ExpensePersistenceError("Failed to list expenses.") from ex

    def count(self, expense_filter: ExpenseFilter) -> int:
        connection = self._require_connection()
        where_sql, params = _build_where(expense_filter)

        try:
            cursor = connection.execute(
                f"SELECT COUNT(*) FROM expenses WHERE {where_sql};", params
            )
            return int(cursor.fetchone()[0])

        except sqlite3.Error as ex:
            raise ExpensePersistenceError("Failed to count expenses.") from ex

    def sum_amount_minor(self, expense_filter: ExpenseFilter) -> int:
        connection = self._require_connection()
        where_sql, params = _build_where(expense_filter)

        try:
            cursor = connection.execute(
                f"SELECT COALESCE(SUM(amount_minor), 0) FROM expenses "
                f"WHERE {where_sql};",
                params,
            )
            return int(cursor.fetchone()[0])

        except sqlite3.Error as ex:
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
        connection = self._require_connection()
        where_sql, params = _build_where(expense_filter)

        try:
            cursor = connection.execute(
                f"SELECT {_COLUMNS} FROM expenses WHERE {where_sql} "
                "ORDER BY amount_minor DESC, expense_date DESC LIMIT ?;",
                (*params, limit),
            )
            return tuple(_deserialize(row) for row in cursor.fetchall())

        except sqlite3.Error as ex:
            raise ExpensePersistenceError(
                "Failed to retrieve largest expenses."
            ) from ex

    def _aggregate_by(
        self, group_expression: str, expense_filter: ExpenseFilter
    ) -> dict[str, int]:
        connection = self._require_connection()
        where_sql, params = _build_where(expense_filter)

        try:
            cursor = connection.execute(
                f"SELECT {group_expression} AS bucket, "
                "SUM(amount_minor) AS total FROM expenses "
                f"WHERE {where_sql} GROUP BY bucket ORDER BY total DESC;",
                params,
            )
            return {row["bucket"]: int(row["total"]) for row in cursor.fetchall()}

        except sqlite3.Error as ex:
            raise ExpensePersistenceError("Failed to aggregate expenses.") from ex

    def _require_connection(self) -> sqlite3.Connection:
        connection = self._connection

        if connection is None:
            raise ExpensePersistenceError(
                "Expense storage has not been initialized."
            )

        return connection

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
        connection = self._require_connection()

        try:
            connection.execute("BEGIN IMMEDIATE;")

            # Get existing expense
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM expenses WHERE expense_id = ?;",
                (expense_id,),
            ).fetchone()

            if row is None:
                connection.rollback()
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
            cursor = connection.execute(
                "UPDATE expenses SET amount_minor = ?, currency = ?, "
                "item = ?, category = ?, expense_date = ?, notes = ?, "
                "updated_at = ? WHERE expense_id = ?;",
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

            if cursor.rowcount == 0:
                connection.rollback()
                raise ExpensePersistenceError(
                    f"Cannot update unknown expense '{expense_id}'."
                )

            connection.commit()

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

        except sqlite3.Error as ex:
            connection.rollback()
            raise ExpensePersistenceError("Failed to update expense by id.") from ex

    def delete_by_id(self, expense_id: str) -> Expense | None:
        """
        Atomically delete an expense by id within a single transaction.

        Returns the deleted expense if it existed, None otherwise.
        """
        connection = self._require_connection()

        try:
            connection.execute("BEGIN IMMEDIATE;")

            # Get existing expense before deletion
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM expenses WHERE expense_id = ?;",
                (expense_id,),
            ).fetchone()

            if row is None:
                connection.rollback()
                return None

            expense = _deserialize(row)

            # Delete the expense
            cursor = connection.execute(
                "DELETE FROM expenses WHERE expense_id = ?;", (expense_id,)
            )

            if cursor.rowcount == 0:
                connection.rollback()
                return None

            connection.commit()
            return expense

        except sqlite3.Error as ex:
            connection.rollback()
            raise ExpensePersistenceError("Failed to delete expense by id.") from ex

    def update_by_match(
        self, expense_filter: ExpenseFilter, *, updates: dict[str, object]
    ) -> Expense:
        """
        Atomically find and update a single expense matching the filter.

        Raises:
            ExpensePersistenceError: If zero or multiple expenses match.
        """
        connection = self._require_connection()

        try:
            connection.execute("BEGIN IMMEDIATE;")

            where_sql, params = _build_where(expense_filter)

            # Find matching expenses
            cursor = connection.execute(
                f"SELECT {_COLUMNS} FROM expenses WHERE {where_sql} "
                "ORDER BY expense_date DESC, created_at DESC;",
                params,
            )
            rows = cursor.fetchall()

            if not rows:
                connection.rollback()
                raise ExpensePersistenceError(
                    "No expense matched the given description."
                )

            if len(rows) > 1:
                connection.rollback()
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
            cursor = connection.execute(
                "UPDATE expenses SET amount_minor = ?, currency = ?, "
                "item = ?, category = ?, expense_date = ?, notes = ?, "
                "updated_at = ? WHERE expense_id = ?;",
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

            if cursor.rowcount == 0:
                connection.rollback()
                raise ExpensePersistenceError(
                    f"Cannot update unknown expense '{expense.id}'."
                )

            connection.commit()

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

        except sqlite3.Error as ex:
            connection.rollback()
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
        connection = self._require_connection()

        try:
            connection.execute("BEGIN IMMEDIATE;")

            where_sql, params = _build_where(expense_filter)

            # Find matching expenses
            cursor = connection.execute(
                f"SELECT {_COLUMNS} FROM expenses WHERE {where_sql} "
                "ORDER BY expense_date DESC, created_at DESC;",
                params,
            )
            rows = cursor.fetchall()

            if not rows:
                connection.rollback()
                raise ExpensePersistenceError(
                    "No expense matched the given description."
                )

            if len(rows) > 1 and not allow_bulk:
                connection.rollback()
                raise ExpensePersistenceError(
                    f"{len(rows)} expenses match this description; "
                    "please specify which one, or explicitly confirm bulk "
                    "deletion."
                )

            deleted = []
            for row in rows:
                expense = _deserialize(row)
                cursor = connection.execute(
                    "DELETE FROM expenses WHERE expense_id = ?;", (expense.id,)
                )
                if cursor.rowcount > 0:
                    deleted.append(expense)

            connection.commit()
            return tuple(deleted)

        except sqlite3.Error as ex:
            connection.rollback()
            raise ExpensePersistenceError("Failed to delete expense by match.") from ex


def _build_where(expense_filter: ExpenseFilter) -> tuple[str, tuple[object, ...]]:
    clauses: list[str] = ["1 = 1"]
    params: list[object] = []

    if expense_filter.period is not None:
        clauses.append("expense_date >= ? AND expense_date <= ?")
        params.append(expense_filter.period.start.isoformat())
        params.append(expense_filter.period.end.isoformat())

    if expense_filter.category is not None:
        clauses.append("LOWER(category) = LOWER(?)")
        params.append(expense_filter.category)

    if expense_filter.item_contains is not None:
        clauses.append("LOWER(item) LIKE ?")
        params.append(f"%{expense_filter.item_contains.lower()}%")

    if expense_filter.min_amount_minor is not None:
        clauses.append("amount_minor >= ?")
        params.append(expense_filter.min_amount_minor)

    if expense_filter.max_amount_minor is not None:
        clauses.append("amount_minor <= ?")
        params.append(expense_filter.max_amount_minor)

    return " AND ".join(clauses), tuple(params)


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


def _deserialize(row: sqlite3.Row) -> Expense:
    return Expense(
        id=row["expense_id"],
        amount_minor=row["amount_minor"],
        currency=row["currency"],
        item=row["item"],
        category=row["category"],
        expense_date=date.fromisoformat(row["expense_date"]),
        notes=row["notes"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
