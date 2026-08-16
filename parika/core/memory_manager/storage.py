"""
PARIKA Memory Storage

This module provides the SQLite persistence layer for the PARIKA
MemoryManager component.

Responsibilities
----------------
- Manage the SQLite database connection.
- Initialize, migrate, and verify the database schema (delegated to
  migrations.py).
- Persist Memory objects.
- Retrieve Memory objects, including scope/kind-filtered and lexical
  (FTS5) search-shaped queries.
- Execute CRUD and mechanical lifecycle operations (touch, select-for-
  consolidation, select-expired/excess, delete-many).
- Serialize and deserialize Memory objects (delegated to
  serialization.py).

This module intentionally contains no business logic and no content
interpretation. Validation, event publication, thread synchronization,
scoring, and consolidation/pruning *policy* are handled by MemoryManager
and retrieval.py. This module only ever compares structural values
(timestamps, counts, an already-computed FTS5 bm25 rank) -- it never
reasons about what a memory's content means.

Thread Safety
-------------
MemoryStorage is not thread-safe. Thread synchronization is the
responsibility of MemoryManager.
"""

from __future__ import annotations

import sqlite3

from datetime import datetime, UTC
from pathlib import Path, PurePath

from parika.core.memory_manager.exceptions import MemoryPersistenceError
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.migrations import configure_database, initialize_schema
from parika.core.memory_manager.search_storage import MEMORY_COLUMNS as _MEMORY_COLUMNS
from parika.core.memory_manager.search_storage import (
    count_by as _search_count_by,
    delete_all as _search_delete_all,
    get_by_category as _search_get_by_category,
    get_by_kind as _search_get_by_kind,
    get_by_scope as _search_get_by_scope,
    list_memories as _search_list_memories,
    search_candidates as _search_candidates,
    select_excess as _search_select_excess,
    select_expired as _search_select_expired,
    select_stale as _search_select_stale,
    touch as _search_touch,
)
from parika.core.memory_manager.serialization import deserialize_memory, serialize_memory


class MemoryStorage:
    """
    SQLite persistence layer for MemoryManager.

    This class is responsible only for persisting and retrieving
    Memory objects. It does not perform business validation,
    publish events, or implement application logic.
    """

    __slots__ = (
        "_database_path",
        "_connection",
    )

    def __init__(
        self,
        database_path: Path,
    ) -> None:
        """
        Initialize a new MemoryStorage instance.

        Parameters
        ----------
        database_path:
            Path to the SQLite database file.
        """

        if not isinstance(database_path, PurePath):
            raise TypeError(
                "database_path must be be a pathlib.Path object."
            )

        self._database_path: Path = database_path
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """
        Initialize the SQLite storage.

        Opens the database connection, configures SQLite, and creates or
        migrates and verifies the schema.

        Raises
        ------
        MemoryPersistenceError
            If initialization fails.
        """

        if self._connection is not None:
            return

        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)

            self._connection = sqlite3.connect(
                check_same_thread=False,
                database=self._database_path,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )

            self._connection.row_factory = sqlite3.Row

            configure_database(self._connection)
            initialize_schema(self._connection)

        except Exception:
            if self._connection is not None:
                try:
                    self._connection.close()
                finally:
                    self._connection = None

            raise

    def shutdown(self) -> None:
        """
        Shutdown the SQLite storage.

        Closes the active database connection.

        Raises
        ------
        MemoryPersistenceError
            If the connection cannot be closed.
        """

        if self._connection is None:
            return

        try:
            self._connection.close()

        except sqlite3.Error as ex:
            raise MemoryPersistenceError(
                "Failed to shutdown memory storage."
            ) from ex

        finally:
            self._connection = None

    def insert(self, memory: Memory) -> Memory:
        """Insert a new memory. Raises MemoryPersistenceError on failure."""

        connection = self._require_connection()

        try:
            row = serialize_memory(memory)
            placeholders = ", ".join("?" for _ in row)

            connection.execute(
                f"INSERT INTO memories ({_MEMORY_COLUMNS}) "
                f"VALUES ({placeholders});",
                row,
            )
            connection.commit()

            return memory

        except sqlite3.Error as ex:
            connection.rollback()
            raise MemoryPersistenceError("Failed to insert memory.") from ex

    def get(self, memory_id: str) -> Memory | None:
        """Retrieve a memory by id, or None. Raises on failure."""

        connection = self._require_connection()

        try:
            cursor = connection.execute(
                f"SELECT {_MEMORY_COLUMNS} FROM memories WHERE memory_id = ?;",
                (memory_id,),
            )

            row = cursor.fetchone()

            return deserialize_memory(row) if row is not None else None

        except sqlite3.Error as ex:
            raise MemoryPersistenceError("Failed to retrieve memory.") from ex

    def update(self, memory: Memory) -> Memory | None:
        """Update an existing memory, or return None if not found."""

        connection = self._require_connection()

        try:
            (
                memory_id,
                kind,
                origin,
                content,
                created_at,
                updated_at,
                tags,
                metadata,
                scope,
                session_id,
                importance_score,
                access_count,
                last_accessed_at,
                decay_at,
                category,
                importance,
                confidence,
            ) = serialize_memory(memory)

            cursor = connection.execute(
                """
                UPDATE memories
                SET
                    kind = ?, origin = ?, content = ?, created_at = ?,
                    updated_at = ?, tags = ?, metadata = ?, scope = ?,
                    session_id = ?, importance_score = ?, access_count = ?,
                    last_accessed_at = ?, decay_at = ?, category = ?,
                    importance = ?, confidence = ?
                WHERE memory_id = ?;
                """,
                (
                    kind, origin, content, created_at, updated_at, tags,
                    metadata, scope, session_id, importance_score,
                    access_count, last_accessed_at, decay_at, category,
                    importance, confidence, memory_id,
                ),
            )

            connection.commit()

            if cursor.rowcount == 0:
                return None

            return memory

        except sqlite3.Error as ex:
            connection.rollback()
            raise MemoryPersistenceError("Failed to update memory.") from ex

    def delete(self, memory_id: str) -> Memory | None:
        """Delete a memory, returning it, or None if not found."""

        connection = self._require_connection()

        try:
            memory = self.get(memory_id)

            if memory is None:
                return None

            connection.execute(
                "DELETE FROM memories WHERE memory_id = ?;", (memory_id,)
            )
            connection.commit()

            return memory

        except sqlite3.Error as ex:
            connection.rollback()
            raise MemoryPersistenceError("Failed to delete memory.") from ex

    def delete_many(self, memory_ids: tuple[str, ...]) -> tuple[Memory, ...]:
        """Delete several memories, returning the ones actually removed."""

        removed: list[Memory] = []

        for memory_id in memory_ids:
            memory = self.delete(memory_id)

            if memory is not None:
                removed.append(memory)

        return tuple(removed)

    def exists(self, memory_id: str) -> bool:
        """Determine whether a memory exists."""

        connection = self._require_connection()

        try:
            cursor = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM memories WHERE memory_id = ?);",
                (memory_id,),
            )

            return bool(cursor.fetchone()[0])

        except sqlite3.Error as ex:
            raise MemoryPersistenceError(
                "Failed to determine memory existence."
            ) from ex

    def count(self) -> int:
        """Return the total number of stored memories."""

        connection = self._require_connection()

        try:
            cursor = connection.execute("SELECT COUNT(*) FROM memories;")

            return int(cursor.fetchone()[0])

        except sqlite3.Error as ex:
            raise MemoryPersistenceError("Failed to count memories.") from ex

    def get_all(self) -> tuple[Memory, ...]:
        """Retrieve all stored memories, ordered by created_at."""

        connection = self._require_connection()

        try:
            cursor = connection.execute(
                f"SELECT {_MEMORY_COLUMNS} FROM memories ORDER BY created_at;"
            )

            return tuple(deserialize_memory(row) for row in cursor.fetchall())

        except sqlite3.Error as ex:
            raise MemoryPersistenceError("Failed to retrieve memories.") from ex

    def get_by_scope(
        self, scope: str, session_id: str | None
    ) -> tuple[Memory, ...]:
        """Retrieve memories matching a scope (and optional session)."""

        return _search_get_by_scope(
            self._require_connection(), scope=scope, session_id=session_id
        )

    def get_by_kind(self, kind: str) -> tuple[Memory, ...]:
        """Retrieve memories matching a kind."""

        return _search_get_by_kind(self._require_connection(), kind=kind)

    def get_by_category(self, category: str) -> tuple[Memory, ...]:
        """Retrieve memories matching a category."""

        return _search_get_by_category(self._require_connection(), category=category)

    def list_memories(
        self,
        *,
        category: str | None,
        scope: str | None,
        session_id: str | None,
        limit: int | None,
    ) -> tuple[Memory, ...]:
        """Retrieve memories matching optional filters, newest-updated first."""

        return _search_list_memories(
            self._require_connection(),
            category=category,
            scope=scope,
            session_id=session_id,
            limit=limit,
        )

    def delete_all(
        self,
        *,
        category: str | None,
        scope: str | None,
        session_id: str | None,
    ) -> tuple[Memory, ...]:
        """Delete every memory matching optional filters; returns removed rows."""

        return _search_delete_all(
            self._require_connection(),
            category=category,
            scope=scope,
            session_id=session_id,
        )

    def count_by(self, *, column: str) -> dict[str, int]:
        """Return a `{value: count}` breakdown for one column."""

        return _search_count_by(self._require_connection(), column=column)

    def touch(self, memory_id: str, *, accessed_at: datetime) -> Memory | None:
        """Bump access_count and last_accessed_at; return the updated Memory."""

        return _search_touch(
            self._require_connection(), memory_id=memory_id, accessed_at=accessed_at
        )

    def search_candidates(
        self,
        *,
        text: str,
        scope: str | None,
        session_id: str | None,
        kind: str | None,
        pool_size: int,
        category: str | None = None,
        require_all_terms: bool = False,
    ) -> tuple[tuple[Memory, float | None], ...]:
        """
        Retrieve a candidate pool for MemoryManager.search(). See
        search_storage.search_candidates() for the lexical (FTS5 bm25)
        matching and filter semantics.
        """

        return _search_candidates(
            self._require_connection(),
            text=text,
            scope=scope,
            session_id=session_id,
            kind=kind,
            pool_size=pool_size,
            category=category,
            require_all_terms=require_all_terms,
        )

    def select_stale(
        self,
        *,
        scope: str,
        session_id: str | None,
        kind: str,
        older_than: datetime,
        max_access_count: int,
    ) -> tuple[Memory, ...]:
        """Read-only selection of consolidation candidates."""

        return _search_select_stale(
            self._require_connection(),
            scope=scope,
            session_id=session_id,
            kind=kind,
            older_than=older_than,
            max_access_count=max_access_count,
        )

    def select_expired(self, *, now: datetime) -> tuple[Memory, ...]:
        """Read-only selection of memories whose decay_at has passed."""

        return _search_select_expired(self._require_connection(), now=now)

    def select_excess(
        self, *, scope: str | None, session_id: str | None, keep_count: int
    ) -> tuple[Memory, ...]:
        """
        Read-only selection of the least-valuable excess memories beyond
        `keep_count`. See search_storage.select_excess().
        """

        return _search_select_excess(
            self._require_connection(),
            scope=scope,
            session_id=session_id,
            keep_count=keep_count,
        )

    def _require_connection(self) -> sqlite3.Connection:
        """Return the active SQLite connection."""

        connection = self._connection

        if connection is None:
            raise MemoryPersistenceError(
                "Memory storage has not been initialized."
            )

        return connection
