"""
Unit tests for `parika/tools/expense/storage.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from parika.tools.expense.exceptions import ExpensePersistenceError
from parika.tools.expense.filters import ExpenseFilter
from parika.tools.expense.model import Expense
from parika.tools.expense.periods import Period
from parika.tools.expense.storage import ExpenseStorage


def _expense(
    *,
    id: str,
    amount_minor: int,
    item: str,
    category: str | None = None,
    expense_date: date,
) -> Expense:
    now = datetime.now(UTC)
    return Expense(
        id=id,
        amount_minor=amount_minor,
        currency="INR",
        item=item,
        category=category,
        expense_date=expense_date,
        notes=None,
        created_at=now,
        updated_at=now,
    )


def _expense_with_updates(
    base: Expense,
    *,
    amount_minor: int | None = None,
    item: str | None = None,
) -> Expense:
    """Create a new Expense with updated fields (since Expense is frozen)."""
    from dataclasses import replace
    return replace(
        base,
        amount_minor=amount_minor if amount_minor is not None else base.amount_minor,
        item=item if item is not None else base.item,
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def storage(tmp_path) -> ExpenseStorage:
    instance = ExpenseStorage(tmp_path / "expense.sqlite3")
    instance.initialize()
    yield instance
    instance.shutdown()


class TestCrud:
    def test_insert_and_get(self, storage: ExpenseStorage) -> None:
        expense = _expense(
            id="e1", amount_minor=200000, item="milk", expense_date=date(2026, 8, 9)
        )
        storage.insert(expense)

        fetched = storage.get("e1")
        assert fetched is not None
        assert fetched.item == "milk"
        assert fetched.amount_minor == 200000

    def test_get_unknown_returns_none(self, storage: ExpenseStorage) -> None:
        assert storage.get("does-not-exist") is None

    def test_update(self, storage: ExpenseStorage) -> None:
        expense = _expense(
            id="e1", amount_minor=200000, item="milk", expense_date=date(2026, 8, 9)
        )
        storage.insert(expense)

        updated = _expense(
            id="e1", amount_minor=180000, item="milk", expense_date=date(2026, 8, 9)
        )
        storage.update(updated)

        assert storage.get("e1").amount_minor == 180000

    def test_update_unknown_raises(self, storage: ExpenseStorage) -> None:
        expense = _expense(
            id="unknown", amount_minor=100, item="x", expense_date=date(2026, 8, 9)
        )
        with pytest.raises(ExpensePersistenceError):
            storage.update(expense)

    def test_delete(self, storage: ExpenseStorage) -> None:
        expense = _expense(
            id="e1", amount_minor=200000, item="milk", expense_date=date(2026, 8, 9)
        )
        storage.insert(expense)

        assert storage.delete("e1") is True
        assert storage.get("e1") is None
        assert storage.delete("e1") is False

    def test_survives_reopening_the_same_database_file(self, tmp_path) -> None:
        path = tmp_path / "expense.sqlite3"

        first = ExpenseStorage(path)
        first.initialize()
        first.insert(
            _expense(id="e1", amount_minor=100, item="x", expense_date=date(2026, 8, 9))
        )
        first.shutdown()

        second = ExpenseStorage(path)
        second.initialize()
        assert second.get("e1") is not None
        second.shutdown()


class TestFilteringAndAggregation:
    @pytest.fixture(autouse=True)
    def _seed(self, storage: ExpenseStorage) -> None:
        storage.insert(
            _expense(
                id="e1",
                amount_minor=120000,
                item="Medicine - self",
                category="Medicine",
                expense_date=date(2026, 8, 1),
            )
        )
        storage.insert(
            _expense(
                id="e2",
                amount_minor=1900,
                item="cramp bandage",
                category="Medicine",
                expense_date=date(2026, 8, 1),
            )
        )
        storage.insert(
            _expense(
                id="e3",
                amount_minor=2000,
                item="KH",
                category=None,
                expense_date=date(2026, 8, 1),
            )
        )
        storage.insert(
            _expense(
                id="e4",
                amount_minor=266600,
                item="reliance + jai maa mart",
                category="Groceries",
                expense_date=date(2026, 8, 2),
            )
        )
        storage.insert(
            _expense(
                id="e5",
                amount_minor=200000,
                item="SIP",
                category="Investment",
                expense_date=date(2026, 8, 5),
            )
        )

    def test_find_with_no_filter_returns_everything(self, storage: ExpenseStorage) -> None:
        assert len(storage.find(ExpenseFilter(), limit=100)) == 5

    def test_find_by_period(self, storage: ExpenseStorage) -> None:
        period = Period(start=date(2026, 8, 1), end=date(2026, 8, 1), label="1 Aug")
        results = storage.find(ExpenseFilter(period=period), limit=100)
        assert {r.id for r in results} == {"e1", "e2", "e3"}

    def test_find_by_category_case_insensitive(self, storage: ExpenseStorage) -> None:
        results = storage.find(ExpenseFilter(category="medicine"), limit=100)
        assert {r.id for r in results} == {"e1", "e2"}

    def test_find_by_item_substring(self, storage: ExpenseStorage) -> None:
        results = storage.find(ExpenseFilter(item_contains="mart"), limit=100)
        assert {r.id for r in results} == {"e4"}

    def test_find_by_amount_range(self, storage: ExpenseStorage) -> None:
        results = storage.find(
            ExpenseFilter(min_amount_minor=100000, max_amount_minor=250000),
            limit=100,
        )
        assert {r.id for r in results} == {"e1", "e5"}

    def test_sum_amount_minor(self, storage: ExpenseStorage) -> None:
        period = Period(start=date(2026, 8, 1), end=date(2026, 8, 1), label="1 Aug")
        assert storage.sum_amount_minor(ExpenseFilter(period=period)) == 123900

    def test_count(self, storage: ExpenseStorage) -> None:
        assert storage.count(ExpenseFilter()) == 5

    def test_aggregate_by_category_uses_uncategorized_label(
        self, storage: ExpenseStorage
    ) -> None:
        totals = storage.aggregate_by_category(ExpenseFilter())
        assert totals["Medicine"] == 121900
        assert totals["Uncategorized"] == 2000
        assert totals["Investment"] == 200000

    def test_aggregate_by_month(self, storage: ExpenseStorage) -> None:
        totals = storage.aggregate_by_month(ExpenseFilter())
        assert list(totals.keys()) == ["2026-08"]
        assert totals["2026-08"] == 120000 + 1900 + 2000 + 266600 + 200000

    def test_largest(self, storage: ExpenseStorage) -> None:
        largest = storage.largest(ExpenseFilter(), limit=2)
        assert [expense.id for expense in largest] == ["e4", "e5"]

    def test_uninitialized_storage_raises(self, tmp_path) -> None:
        uninitialized = ExpenseStorage(tmp_path / "other.sqlite3")
        with pytest.raises(ExpensePersistenceError):
            uninitialized.get("e1")


class TestConcurrency:
    """Tests for multi-connection SQLite concurrency (WAL mode)."""

    def test_two_instances_same_database(self, tmp_path) -> None:
        """Two ExpenseStorage instances can open the same database file."""
        path = tmp_path / "expense.sqlite3"

        storage1 = ExpenseStorage(path)
        storage1.initialize()

        storage2 = ExpenseStorage(path)
        storage2.initialize()

        try:
            expense = _expense(
                id="e1", amount_minor=100, item="test", expense_date=date(2026, 8, 9)
            )
            storage1.insert(expense)

            # Both instances can read the data
            fetched1 = storage1.get("e1")
            fetched2 = storage2.get("e1")

            assert fetched1 is not None
            assert fetched2 is not None
            assert fetched1.item == "test"
            assert fetched2.item == "test"
        finally:
            storage1.shutdown()
            storage2.shutdown()

    def test_separate_connections(self, tmp_path) -> None:
        """Each ExpenseStorage instance owns a separate SQLite connection."""
        path = tmp_path / "expense.sqlite3"

        storage1 = ExpenseStorage(path)
        storage1.initialize()

        storage2 = ExpenseStorage(path)
        storage2.initialize()

        try:
            # Verify they are different connection objects
            conn1 = storage1._connection
            conn2 = storage2._connection
            assert conn1 is not conn2
        finally:
            storage1.shutdown()
            storage2.shutdown()

    def test_no_thread_affinity_error_same_thread(self, tmp_path) -> None:
        """No SQLite thread-affinity error when connection used from owning thread."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            # Use from the same thread that initialized it - should work
            expense = _expense(
                id="e1", amount_minor=100, item="test", expense_date=date(2026, 8, 9)
            )
            storage.insert(expense)
            fetched = storage.get("e1")
            assert fetched is not None
        finally:
            storage.shutdown()

    def test_wal_mode_enabled(self, tmp_path) -> None:
        """WAL mode is enabled for the database."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            # Check journal_mode via PRAGMA
            conn = storage._connection
            cursor = conn.execute("PRAGMA journal_mode;")
            mode = cursor.fetchone()[0]
            assert mode.upper() == "WAL"
        finally:
            storage.shutdown()

    def test_busy_timeout_configured(self, tmp_path) -> None:
        """busy_timeout is configured."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            conn = storage._connection
            cursor = conn.execute("PRAGMA busy_timeout;")
            timeout = cursor.fetchone()[0]
            assert timeout == 5000
        finally:
            storage.shutdown()

    def test_concurrent_reads(self, tmp_path) -> None:
        """Multiple connections can read concurrently."""
        path = tmp_path / "expense.sqlite3"

        storage1 = ExpenseStorage(path)
        storage1.initialize()
        storage2 = ExpenseStorage(path)
        storage2.initialize()

        try:
            # Seed data
            for i in range(10):
                storage1.insert(_expense(
                    id=f"e{i}", amount_minor=100 * i, item=f"item{i}", expense_date=date(2026, 8, 9)
                ))

            # Both can read
            results1 = storage1.find(ExpenseFilter(), limit=100)
            results2 = storage2.find(ExpenseFilter(), limit=100)

            assert len(results1) == 10
            assert len(results2) == 10
        finally:
            storage1.shutdown()
            storage2.shutdown()

    def test_concurrent_write_and_read(self, tmp_path) -> None:
        """Write on one connection, read on another works."""
        path = tmp_path / "expense.sqlite3"

        writer = ExpenseStorage(path)
        writer.initialize()
        reader = ExpenseStorage(path)
        reader.initialize()

        try:
            writer.insert(_expense(id="e1", amount_minor=100, item="write", expense_date=date(2026, 8, 9)))
            fetched = reader.get("e1")
            assert fetched is not None
            assert fetched.item == "write"
        finally:
            writer.shutdown()
            reader.shutdown()

    def test_concurrent_read_and_write(self, tmp_path) -> None:
        """Read on one connection while write on another works."""
        path = tmp_path / "expense.sqlite3"

        writer = ExpenseStorage(path)
        writer.initialize()
        reader = ExpenseStorage(path)
        reader.initialize()

        try:
            # Seed
            writer.insert(_expense(id="e1", amount_minor=100, item="original", expense_date=date(2026, 8, 9)))

            # Read while writer updates
            fetched = reader.get("e1")
            assert fetched.item == "original"

            writer.insert(_expense(id="e2", amount_minor=200, item="new", expense_date=date(2026, 8, 9)))

            # Reader sees new data
            all_items = reader.find(ExpenseFilter(), limit=100)
            assert len(all_items) == 2
        finally:
            writer.shutdown()
            reader.shutdown()

    def test_concurrent_writes_serialized(self, tmp_path) -> None:
        """Concurrent writes from different connections are serialized by SQLite."""
        import threading
        import time

        path = tmp_path / "expense.sqlite3"

        results = {"errors": [], "counts": []}

        def writer_thread(thread_id: int, count: int):
            storage = ExpenseStorage(path)
            storage.initialize()
            try:
                for i in range(count):
                    expense_id = f"t{thread_id}_e{i}"
                    storage.insert(_expense(
                        id=expense_id, amount_minor=100, item=f"thread{thread_id}", expense_date=date(2026, 8, 9)
                    ))
                results["counts"].append(count)
            except Exception as e:
                results["errors"].append(e)
            finally:
                storage.shutdown()

        threads = [threading.Thread(target=writer_thread, args=(i, 50)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results["errors"]) == 0, f"Errors: {results['errors']}"
        assert sum(results["counts"]) == 250

        # Verify all inserted
        verify = ExpenseStorage(path)
        verify.initialize()
        try:
            all_expenses = verify.find(ExpenseFilter(), limit=1000)
            assert len(all_expenses) == 250
        finally:
            verify.shutdown()

    def test_update_preserves_atomic_semantics(self, tmp_path) -> None:
        """update() preserves its atomic semantics (single statement)."""
        path = tmp_path / "expense.sqlite3"

        storage1 = ExpenseStorage(path)
        storage1.initialize()
        storage2 = ExpenseStorage(path)
        storage2.initialize()

        try:
            storage1.insert(_expense(id="e1", amount_minor=100, item="test", expense_date=date(2026, 8, 9)))

            # Update from storage1 - create new expense with updated amount
            expense = storage1.get("e1")
            updated_expense = _expense_with_updates(expense, amount_minor=200)
            storage1.update(updated_expense)

            # storage2 sees updated value
            fetched = storage2.get("e1")
            assert fetched.amount_minor == 200
        finally:
            storage1.shutdown()
            storage2.shutdown()

    def test_delete_preserves_atomic_semantics(self, tmp_path) -> None:
        """delete() preserves its atomic semantics (single statement)."""
        path = tmp_path / "expense.sqlite3"

        storage1 = ExpenseStorage(path)
        storage1.initialize()
        storage2 = ExpenseStorage(path)
        storage2.initialize()

        try:
            storage1.insert(_expense(id="e1", amount_minor=100, item="test", expense_date=date(2026, 8, 9)))

            # Delete from storage1
            storage1.delete("e1")

            # storage2 sees deletion
            assert storage2.get("e1") is None
        finally:
            storage1.shutdown()
            storage2.shutdown()

    def test_failed_operation_rollbacks(self, tmp_path) -> None:
        """Failed operations rollback correctly."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            storage.insert(_expense(id="e1", amount_minor=100, item="test", expense_date=date(2026, 8, 9)))

            # Try to insert duplicate ID - should fail and rollback
            with pytest.raises(ExpensePersistenceError):
                storage.insert(_expense(id="e1", amount_minor=200, item="duplicate", expense_date=date(2026, 8, 9)))

            # Original should be unchanged
            fetched = storage.get("e1")
            assert fetched.amount_minor == 100
            assert fetched.item == "test"
        finally:
            storage.shutdown()

    def test_compound_update_by_id_atomicity_not_guaranteed_by_storage(self, tmp_path) -> None:
        """
        Note: Compound operations like update_by_id (get + update) are NOT
        atomic at the Storage level. This is a Service layer concern.
        This test documents the current behavior.
        """
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            storage.insert(_expense(id="e1", amount_minor=100, item="test", expense_date=date(2026, 8, 9)))

            # Service layer does: get() -> modify -> update()
            # This is NOT atomic at Storage level
            expense = storage.get("e1")
            updated_expense = _expense_with_updates(expense, amount_minor=200)
            storage.update(updated_expense)

            # Works in single-threaded case
            assert storage.get("e1").amount_minor == 200
        finally:
            storage.shutdown()

    def test_compound_delete_by_id_atomicity_not_guaranteed_by_storage(self, tmp_path) -> None:
        """
        Note: Compound operations like delete_by_id (get + delete) are NOT
        atomic at the Storage level. This is a Service layer concern.
        """
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            storage.insert(_expense(id="e1", amount_minor=100, item="test", expense_date=date(2026, 8, 9)))

            # Service layer does: get() -> delete()
            expense = storage.get("e1")
            assert expense is not None
            storage.delete("e1")

            assert storage.get("e1") is None
        finally:
            storage.shutdown()

    def test_update_by_id_atomic(self, tmp_path) -> None:
        """update_by_id is atomic - read-modify-write in single transaction."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            storage.insert(_expense(id="e1", amount_minor=100, item="test", expense_date=date(2026, 8, 9)))

            updated = storage.update_by_id("e1", updates={"amount_minor": 200})
            assert updated.amount_minor == 200
            assert updated.item == "test"
            assert storage.get("e1").amount_minor == 200
        finally:
            storage.shutdown()

    def test_update_by_id_not_found_raises(self, tmp_path) -> None:
        """update_by_id raises when expense doesn't exist."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            with pytest.raises(ExpensePersistenceError, match="unknown expense"):
                storage.update_by_id("nonexistent", updates={"amount_minor": 200})
        finally:
            storage.shutdown()

    def test_delete_by_id_atomic(self, tmp_path) -> None:
        """delete_by_id is atomic - read-delete in single transaction."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            storage.insert(_expense(id="e1", amount_minor=100, item="test", expense_date=date(2026, 8, 9)))

            deleted = storage.delete_by_id("e1")
            assert deleted is not None
            assert deleted.amount_minor == 100
            assert deleted.item == "test"
            assert storage.get("e1") is None
        finally:
            storage.shutdown()

    def test_delete_by_id_not_found_returns_none(self, tmp_path) -> None:
        """delete_by_id returns None when expense doesn't exist."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            result = storage.delete_by_id("nonexistent")
            assert result is None
        finally:
            storage.shutdown()

    def test_update_by_match_atomic(self, tmp_path) -> None:
        """update_by_match is atomic - find-validate-update in single transaction."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            storage.insert(_expense(id="e1", amount_minor=100, item="milk", expense_date=date(2026, 8, 9)))

            updated = storage.update_by_match(
                ExpenseFilter(item_contains="milk"), updates={"amount_minor": 200}
            )
            assert updated.amount_minor == 200
            assert updated.item == "milk"
            assert storage.get("e1").amount_minor == 200
        finally:
            storage.shutdown()

    def test_update_by_match_not_found_raises(self, tmp_path) -> None:
        """update_by_match raises when no match found."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            with pytest.raises(ExpensePersistenceError, match="No expense matched"):
                storage.update_by_match(
                    ExpenseFilter(item_contains="nonexistent"), updates={"amount_minor": 200}
                )
        finally:
            storage.shutdown()

    def test_update_by_match_ambiguous_raises(self, tmp_path) -> None:
        """update_by_match raises when multiple matches found."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            storage.insert(_expense(id="e1", amount_minor=100, item="milk", expense_date=date(2026, 8, 9)))
            storage.insert(_expense(id="e2", amount_minor=200, item="milk", expense_date=date(2026, 8, 9)))

            with pytest.raises(ExpensePersistenceError, match="match this description"):
                storage.update_by_match(
                    ExpenseFilter(item_contains="milk"), updates={"amount_minor": 300}
                )
        finally:
            storage.shutdown()

    def test_delete_by_match_atomic(self, tmp_path) -> None:
        """delete_by_match is atomic - find-validate-delete in single transaction."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            storage.insert(_expense(id="e1", amount_minor=100, item="milk", expense_date=date(2026, 8, 9)))

            deleted = storage.delete_by_match(ExpenseFilter(item_contains="milk"))
            assert len(deleted) == 1
            assert deleted[0].amount_minor == 100
            assert storage.get("e1") is None
        finally:
            storage.shutdown()

    def test_delete_by_match_not_found_raises(self, tmp_path) -> None:
        """delete_by_match raises when no match found."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            with pytest.raises(ExpensePersistenceError, match="No expense matched"):
                storage.delete_by_match(ExpenseFilter(item_contains="nonexistent"))
        finally:
            storage.shutdown()

    def test_delete_by_match_ambiguous_raises_without_bulk(self, tmp_path) -> None:
        """delete_by_match raises when multiple matches and allow_bulk=False."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            storage.insert(_expense(id="e1", amount_minor=100, item="milk", expense_date=date(2026, 8, 9)))
            storage.insert(_expense(id="e2", amount_minor=200, item="milk", expense_date=date(2026, 8, 9)))

            with pytest.raises(ExpensePersistenceError, match="match this description"):
                storage.delete_by_match(ExpenseFilter(item_contains="milk"), allow_bulk=False)
        finally:
            storage.shutdown()

    def test_delete_by_match_bulk_deletes_all(self, tmp_path) -> None:
        """delete_by_match with allow_bulk=True deletes all matches."""
        path = tmp_path / "expense.sqlite3"

        storage = ExpenseStorage(path)
        storage.initialize()

        try:
            storage.insert(_expense(id="e1", amount_minor=100, item="milk", expense_date=date(2026, 8, 9)))
            storage.insert(_expense(id="e2", amount_minor=200, item="milk", expense_date=date(2026, 8, 9)))

            deleted = storage.delete_by_match(ExpenseFilter(item_contains="milk"), allow_bulk=True)
            assert len(deleted) == 2
            assert storage.get("e1") is None
            assert storage.get("e2") is None
        finally:
            storage.shutdown()

    def test_concurrent_update_by_id_atomic(self, tmp_path) -> None:
        """Concurrent update_by_id calls are serialized and atomic."""
        import threading

        path = tmp_path / "expense.sqlite3"

        storage1 = ExpenseStorage(path)
        storage1.initialize()
        storage1.insert(_expense(id="e1", amount_minor=100, item="test", expense_date=date(2026, 8, 9)))
        storage1.shutdown()

        results = {"errors": [], "values": []}

        def worker(worker_id: int, new_amount: int):
            storage = ExpenseStorage(path)
            storage.initialize()
            try:
                updated = storage.update_by_id("e1", updates={"amount_minor": new_amount})
                results["values"].append(updated.amount_minor)
            except Exception as e:
                results["errors"].append(e)
            finally:
                storage.shutdown()

        t1 = threading.Thread(target=worker, args=(1, 200))
        t2 = threading.Thread(target=worker, args=(2, 300))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results["errors"]) == 0

        # Verify final state - one of the updates won
        verify = ExpenseStorage(path)
        verify.initialize()
        try:
            final = verify.get("e1")
            assert final.amount_minor in (200, 300)
        finally:
            verify.shutdown()

    def test_concurrent_delete_by_id_atomic(self, tmp_path) -> None:
        """Concurrent delete_by_id calls are serialized - only one succeeds."""
        import threading

        path = tmp_path / "expense.sqlite3"

        storage1 = ExpenseStorage(path)
        storage1.initialize()
        storage1.insert(_expense(id="e1", amount_minor=100, item="test", expense_date=date(2026, 8, 9)))
        storage1.shutdown()

        results = {"errors": [], "deleted_count": 0}

        def worker(worker_id: int):
            storage = ExpenseStorage(path)
            storage.initialize()
            try:
                deleted = storage.delete_by_id("e1")
                if deleted is not None:
                    results["deleted_count"] += 1
            except Exception as e:
                results["errors"].append(e)
            finally:
                storage.shutdown()

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results["errors"]) == 0
        assert results["deleted_count"] == 1

        # Verify final state
        verify = ExpenseStorage(path)
        verify.initialize()
        try:
            assert verify.get("e1") is None
        finally:
            verify.shutdown()

    def test_concurrent_update_by_match_atomic(self, tmp_path) -> None:
        """Concurrent update_by_match calls are serialized and atomic."""
        import threading

        path = tmp_path / "expense.sqlite3"

        storage1 = ExpenseStorage(path)
        storage1.initialize()
        storage1.insert(_expense(id="e1", amount_minor=100, item="milk", expense_date=date(2026, 8, 9)))
        storage1.shutdown()

        results = {"errors": [], "values": []}

        def worker(worker_id: int, new_amount: int):
            storage = ExpenseStorage(path)
            storage.initialize()
            try:
                updated = storage.update_by_match(
                    ExpenseFilter(item_contains="milk"), updates={"amount_minor": new_amount}
                )
                results["values"].append(updated.amount_minor)
            except Exception as e:
                results["errors"].append(e)
            finally:
                storage.shutdown()

        t1 = threading.Thread(target=worker, args=(1, 200))
        t2 = threading.Thread(target=worker, args=(2, 300))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results["errors"]) == 0

        verify = ExpenseStorage(path)
        verify.initialize()
        try:
            final = verify.get("e1")
            assert final.amount_minor in (200, 300)
        finally:
            verify.shutdown()

    def test_concurrent_delete_by_match_atomic(self, tmp_path) -> None:
        """Concurrent delete_by_match calls are serialized - only one succeeds."""
        import threading

        path = tmp_path / "expense.sqlite3"

        storage1 = ExpenseStorage(path)
        storage1.initialize()
        storage1.insert(_expense(id="e1", amount_minor=100, item="milk", expense_date=date(2026, 8, 9)))
        storage1.shutdown()

        results = {"errors": [], "deleted_count": 0, "not_found_count": 0}

        def worker(worker_id: int):
            storage = ExpenseStorage(path)
            storage.initialize()
            try:
                deleted = storage.delete_by_match(ExpenseFilter(item_contains="milk"))
                results["deleted_count"] += len(deleted)
            except ExpensePersistenceError as e:
                if "No expense matched" in str(e):
                    results["not_found_count"] += 1
                else:
                    results["errors"].append(e)
            except Exception as e:
                results["errors"].append(e)
            finally:
                storage.shutdown()

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(results["errors"]) == 0
        assert results["deleted_count"] == 1
        assert results["not_found_count"] == 1

        verify = ExpenseStorage(path)
        verify.initialize()
        try:
            assert verify.get("e1") is None
        finally:
            verify.shutdown()
