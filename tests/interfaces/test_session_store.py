"""Unit tests for PostgreSQLSessionStore."""


from __future__ import annotations
from tests.conftest_db import build_test_db_config

from collections.abc import Iterator
from pathlib import Path

import pytest

from parika.interfaces.postgresql_session_store import PostgreSQLSessionStore, SessionNotFoundError, SessionPersistenceError
from parika.core.database.pool import PoolManager
from parika.core.database.config import DatabaseConfig


# Test database configuration
# Test database configuration from environment
# TEST_DATABASE_CONFIG = { ... }  # Replaced by build_test_db_config()


@pytest.fixture(scope="session")
def _test_db_pool():
    """Initialize PostgreSQL test pool for the test session."""
    db_config = build_test_db_config()
    pool = PoolManager.initialize_sync_pool(db_config)
    yield pool
    PoolManager.shutdown_sync_pool()


@pytest.fixture
def store(_test_db_pool) -> Iterator[PostgreSQLSessionStore]:
    store = PostgreSQLSessionStore(_test_db_pool)
    store.initialize()
    # Clean up before each test
    with _test_db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM core.session_message;")
            cur.execute("DELETE FROM core.session;")
            conn.commit()

    yield store

    store.shutdown()


class TestPostgreSQLSessionStore:
    def test_ensure_session_is_idempotent(self, store: PostgreSQLSessionStore) -> None:
        store.ensure_session("s1")
        store.ensure_session("s1")

        assert len(store.list_sessions()) == 1

    def test_append_message_auto_creates_session(self, store: PostgreSQLSessionStore) -> None:
        store.append_message("s1", role="user", content="hello")

        summary = store.get_session("s1")
        assert summary is not None
        assert summary.message_count == 1

    def test_append_message_increments_count(self, store: PostgreSQLSessionStore) -> None:
        store.append_message("s1", role="user", content="hello")
        store.append_message("s1", role="assistant", content="hi there")

        summary = store.get_session("s1")
        assert summary is not None
        assert summary.message_count == 2

    def test_get_messages_returns_in_order(self, store: PostgreSQLSessionStore) -> None:
        store.append_message("s1", role="user", content="first")
        store.append_message("s1", role="assistant", content="second")

        messages = store.get_messages("s1")

        assert [m.content for m in messages] == ["first", "second"]

    def test_set_title_and_summary(self, store: PostgreSQLSessionStore) -> None:
        store.ensure_session("s1")
        store.set_title("s1", "My Title")
        store.set_summary("s1", "A short summary.")

        summary = store.get_session("s1")
        assert summary is not None
        assert summary.title == "My Title"
        assert summary.summary == "A short summary."

    def test_set_title_raises_when_session_missing(self, store: PostgreSQLSessionStore) -> None:
        with pytest.raises(SessionNotFoundError):
            store.set_title("missing", "x")

    def test_get_session_returns_none_when_missing(self, store: PostgreSQLSessionStore) -> None:
        assert store.get_session("missing") is None

    def test_list_sessions_orders_by_updated_at_desc(self, store: PostgreSQLSessionStore) -> None:
        store.append_message("s1", role="user", content="a")
        store.append_message("s2", role="user", content="b")
        store.append_message("s1", role="user", content="c")  # bumps s1's updated_at

        summaries = store.list_sessions()

        assert summaries[0].session_id == "s1"

    def test_search_messages_matches_content(self, store: PostgreSQLSessionStore) -> None:
        store.append_message("s1", role="user", content="I like dark mode themes")
        store.append_message("s2", role="user", content="unrelated cooking content")

        results = store.search_messages("dark mode")

        assert len(results) == 1
        assert results[0].session_id == "s1"

    def test_search_messages_with_punctuation_does_not_raise(
        self, store: PostgreSQLSessionStore
    ) -> None:
        """
        Regression test: see the identical test/rationale in
        tests/core/memory_manager/test_memory_manager_search.py.
        """
        store.append_message("s1", role="user", content="User works at Acme.")

        results = store.search_messages("User works at Acme.")

        assert len(results) == 1

    def test_search_messages_returns_empty_when_no_match(self, store: PostgreSQLSessionStore) -> None:
        store.append_message("s1", role="user", content="hello world")

        assert store.search_messages("nonexistent") == ()

    def test_reinitialize_is_idempotent(self, store: PostgreSQLSessionStore) -> None:
        store.append_message("s1", role="user", content="hello")
        store.initialize()

        assert store.get_session("s1") is not None


class TestDeleteSession:
    def test_deletes_session_and_messages(self, store: PostgreSQLSessionStore) -> None:
        store.append_message("s1", role="user", content="hello")

        deleted = store.delete_session("s1")

        assert deleted is True
        assert store.get_session("s1") is None
        assert store.get_messages("s1") == ()

    def test_returns_false_when_session_missing(self, store: PostgreSQLSessionStore) -> None:
        assert store.delete_session("missing") is False


class TestExportImportSession:
    def test_export_writes_json_file(self, store: PostgreSQLSessionStore, tmp_path: Path) -> None:
        store.append_message("s1", role="user", content="hello")
        store.append_message("s1", role="assistant", content="hi there")
        store.set_title("s1", "My Session")
        export_path = tmp_path / "session.json"

        count = store.export_session("s1", path=export_path)

        assert count == 2
        assert export_path.exists()

    def test_export_raises_when_session_missing(
        self, store: PostgreSQLSessionStore, tmp_path: Path
    ) -> None:
        with pytest.raises(SessionNotFoundError):
            store.export_session("missing", path=tmp_path / "x.json")

    def test_import_restores_session_and_messages(
        self, store: PostgreSQLSessionStore, tmp_path: Path
    ) -> None:
        store.append_message("s1", role="user", content="hello")
        store.append_message("s1", role="assistant", content="hi there")
        store.set_title("s1", "My Session")
        export_path = tmp_path / "session.json"
        store.export_session("s1", path=export_path)
        store.delete_session("s1")

        imported_id = store.import_session(path=export_path)

        assert imported_id == "s1"
        summary = store.get_session(imported_id)
        assert summary is not None
        assert summary.title == "My Session"
        assert [m.content for m in store.get_messages(imported_id)] == ["hello", "hi there"]

    def test_import_generates_fresh_id_on_collision(
        self, store: PostgreSQLSessionStore, tmp_path: Path
    ) -> None:
        store.append_message("s1", role="user", content="hello")
        export_path = tmp_path / "session.json"
        store.export_session("s1", path=export_path)
        # s1 still exists (not deleted) -- import must not collide with it.

        imported_id = store.import_session(path=export_path)

        assert imported_id != "s1"
        assert store.get_session(imported_id) is not None
