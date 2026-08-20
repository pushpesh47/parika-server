"""
PARIKA Memory Storage - PostgreSQL Implementation

PostgreSQL persistence layer for the PARIKA MemoryManager component.
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from pathlib import Path, PurePath
from types import MappingProxyType
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from parika.core.memory_manager.exceptions import MemoryPersistenceError
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.memory_category import MemoryCategory
from parika.core.memory_manager.memory_importance import MemoryImportance
from parika.core.memory_manager.memory_kind import MemoryKind
from parika.core.memory_manager.memory_origin import MemoryOrigin
from parika.core.memory_manager.memory_scope import MemoryScope
from parika.core.memory_manager.postgresql_search_storage import MEMORY_COLUMNS as _MEMORY_COLUMNS
from parika.core.memory_manager.postgresql_serialization import deserialize_memory, serialize_memory


class PostgreSQLMemoryStorage:
    """PostgreSQL persistence layer for MemoryManager."""

    __slots__ = ("_pool",)

    def __init__(self, pool) -> None:
        """
        Initialize with a PostgreSQL connection pool.

        Args:
            pool: psycopg_pool.ConnectionPool instance
        """
        self._pool = pool

    def initialize(self) -> None:
        """No-op: schema is managed by Alembic migrations."""
        pass

    def shutdown(self) -> None:
        """No-op: pool is managed by PoolManager."""
        pass

    def _require_connection(self):
        return self._pool.connection()

    def insert(self, memory: Memory) -> Memory:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    row = serialize_memory(memory)
                    placeholders = ", ".join(["%s"] * len(row))
                    columns = _MEMORY_COLUMNS.replace(", ", ", ")
                    cur.execute(
                        f"INSERT INTO core.memory ({columns}) VALUES ({placeholders})",
                        row,
                    )
                    conn.commit()
                    return memory
                except psycopg.Error as ex:
                    conn.rollback()
                    raise MemoryPersistenceError("Failed to insert memory.") from ex

    def get(self, memory_id: str) -> Memory | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        f"SELECT {_MEMORY_COLUMNS} FROM core.memory WHERE memory_id = %s",
                        (memory_id,),
                    )
                    row = cur.fetchone()
                    return deserialize_memory(row) if row else None
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to retrieve memory.") from ex

    def update(self, memory: Memory) -> Memory | None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
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

                    cur.execute(
                        """
                        UPDATE core.memory
                        SET kind = %s, origin = %s, content = %s, created_at = %s,
                            updated_at = %s, tags = %s, metadata = %s, scope = %s,
                            session_id = %s, importance_score = %s, access_count = %s,
                            last_accessed_at = %s, decay_at = %s, category = %s,
                            importance = %s, confidence = %s
                        WHERE memory_id = %s
                        """,
                        (
                            kind, origin, content, created_at, updated_at, tags,
                            metadata, scope, session_id, importance_score,
                            access_count, last_accessed_at, decay_at, category,
                            importance, confidence, memory_id,
                        ),
                    )
                    conn.commit()

                    if cur.rowcount == 0:
                        return None
                    return memory
                except psycopg.Error as ex:
                    conn.rollback()
                    raise MemoryPersistenceError("Failed to update memory.") from ex

    def delete(self, memory_id: str) -> Memory | None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    memory = self.get(memory_id)
                    if memory is None:
                        return None

                    cur.execute("DELETE FROM core.memory WHERE memory_id = %s", (memory_id,))
                    conn.commit()
                    return memory
                except psycopg.Error as ex:
                    conn.rollback()
                    raise MemoryPersistenceError("Failed to delete memory.") from ex

    def delete_many(self, memory_ids: tuple[str, ...]) -> tuple[Memory, ...]:
        removed = []
        for memory_id in memory_ids:
            memory = self.delete(memory_id)
            if memory is not None:
                removed.append(memory)
        return tuple(removed)

    def exists(self, memory_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "SELECT EXISTS(SELECT 1 FROM core.memory WHERE memory_id = %s)",
                        (memory_id,),
                    )
                    return bool(cur.fetchone()[0])
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to determine memory existence.") from ex

    def count(self) -> int:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("SELECT COUNT(*) FROM core.memory")
                    return int(cur.fetchone()[0])
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to count memories.") from ex

    def get_all(self) -> tuple[Memory, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(f"SELECT {_MEMORY_COLUMNS} FROM core.memory ORDER BY created_at")
                    return tuple(deserialize_memory(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to retrieve memories.") from ex

    def get_by_scope(self, scope: str, session_id: str | None) -> tuple[Memory, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    if session_id:
                        cur.execute(
                            f"SELECT {_MEMORY_COLUMNS} FROM core.memory WHERE scope = %s AND session_id = %s ORDER BY created_at",
                            (scope, session_id),
                        )
                    else:
                        cur.execute(
                            f"SELECT {_MEMORY_COLUMNS} FROM core.memory WHERE scope = %s ORDER BY created_at",
                            (scope,),
                        )
                    return tuple(deserialize_memory(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to retrieve memories by scope.") from ex

    def get_by_kind(self, kind: str) -> tuple[Memory, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        f"SELECT {_MEMORY_COLUMNS} FROM core.memory WHERE kind = %s ORDER BY created_at",
                        (kind,),
                    )
                    return tuple(deserialize_memory(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to retrieve memories by kind.") from ex

    def get_by_category(self, category: str) -> tuple[Memory, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        f"SELECT {_MEMORY_COLUMNS} FROM core.memory WHERE category = %s ORDER BY created_at",
                        (category,),
                    )
                    return tuple(deserialize_memory(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to retrieve memories by category.") from ex

    def list_memories(
        self,
        *,
        category: str | None,
        scope: str | None,
        session_id: str | None,
        limit: int | None,
    ) -> tuple[Memory, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    where_clauses = []
                    params = []
                    if category:
                        where_clauses.append("category = %s")
                        params.append(category)
                    if scope:
                        where_clauses.append("scope = %s")
                        params.append(scope)
                    if session_id:
                        where_clauses.append("session_id = %s")
                        params.append(session_id)
                    
                    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
                    limit_sql = f" LIMIT %s" if limit else ""
                    if limit:
                        params.append(limit)
                    
                    cur.execute(
                        f"SELECT {_MEMORY_COLUMNS} FROM core.memory{where_sql} ORDER BY created_at{limit_sql}",
                        tuple(params),
                    )
                    return tuple(deserialize_memory(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to list memories.") from ex

    def delete_all(self, *, category: str | None, scope: str | None, session_id: str | None) -> tuple[Memory, ...]:
        removed = []
        memories = self.list_memories(category=category, scope=scope, session_id=session_id, limit=None)
        for memory in memories:
            self.delete(memory.memory_id)
            removed.append(memory)
        return tuple(removed)

    def count_by(self, *, column: str) -> dict[str, int]:
        if column not in {"category", "importance", "scope"}:
            raise MemoryPersistenceError(f"Cannot aggregate by column '{column}'.")

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        f"SELECT {column} AS value, COUNT(*) AS total FROM core.memory GROUP BY {column};"
                    )
                    return {row[0]: int(row[1]) for row in cur.fetchall()}
                except psycopg.Error as ex:
                    raise MemoryPersistenceError(f"Failed to aggregate memories by '{column}'.") from ex

    def touch(self, memory_id: str, *, accessed_at: datetime) -> Memory | None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        UPDATE core.memory
                        SET access_count = access_count + 1, last_accessed_at = %s
                        WHERE memory_id = %s;
                        """,
                        (accessed_at.isoformat(), memory_id),
                    )
                    conn.commit()

                    if cur.rowcount == 0:
                        return None

                    cur.execute(
                        f"SELECT {_MEMORY_COLUMNS} FROM core.memory WHERE memory_id = %s;",
                        (memory_id,),
                    )
                    row = cur.fetchone()
                    return deserialize_memory(row) if row else None
                except psycopg.Error as ex:
                    conn.rollback()
                    raise MemoryPersistenceError("Failed to touch memory.") from ex

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
        PostgreSQL FTS search using tsvector.
        """
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    # Build the search query
                    if require_all_terms:
                        # Use plainto_tsquery for AND semantics
                        query = "plainto_tsquery('simple', %s)"
                    else:
                        # Use websearch_to_tsquery for OR semantics (more forgiving)
                        query = "websearch_to_tsquery('simple', %s)"

                    where_clauses = ["search_vector @@ " + query]
                    params = [text, text]  # text for WHERE clause, text for ts_rank_cd

                    if scope:
                        where_clauses.append("scope = %s")
                        params.append(scope)
                    if session_id:
                        where_clauses.append("session_id = %s")
                        params.append(session_id)
                    if kind:
                        where_clauses.append("kind = %s")
                        params.append(kind)
                    if category:
                        where_clauses.append("category = %s")
                        params.append(category)

                    where_sql = " AND ".join(where_clauses)

                    cur.execute(
                        f"""
                        SELECT {_MEMORY_COLUMNS},
                               ts_rank_cd(search_vector, {query}) AS rank
                        FROM core.memory
                        WHERE {where_sql}
                        ORDER BY rank DESC
                        LIMIT %s
                        """,
                        (*params, pool_size),
                    )

                    return tuple(
                        (deserialize_memory(row), float(row["rank"])) for row in cur.fetchall()
                    )
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to search memories.") from ex

    def select_stale(
        self,
        *,
        scope: str,
        session_id: str | None,
        kind: str,
        older_than: datetime,
        max_access_count: int,
    ) -> tuple[Memory, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    where = ["scope = %s", "kind = %s", "created_at < %s", "access_count <= %s"]
                    params = [scope, kind, older_than.isoformat(), max_access_count]
                    if session_id:
                        where.append("session_id = %s")
                        params.append(session_id)
                    
                    cur.execute(
                        f"SELECT {_MEMORY_COLUMNS} FROM core.memory WHERE {' AND '.join(where)} ORDER BY created_at",
                        tuple(params),
                    )
                    return tuple(deserialize_memory(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to select stale memories.") from ex

    def select_expired(self, *, now: datetime) -> tuple[Memory, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        f"SELECT {_MEMORY_COLUMNS} FROM core.memory WHERE decay_at IS NOT NULL AND decay_at < %s ORDER BY created_at",
                        (now.isoformat(),),
                    )
                    return tuple(deserialize_memory(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to select expired memories.") from ex

    def select_excess(
        self, *, scope: str | None, session_id: str | None, keep_count: int
    ) -> tuple[Memory, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    where = []
                    params = []
                    if scope:
                        where.append("scope = %s")
                        params.append(scope)
                    if session_id:
                        where.append("session_id = %s")
                        params.append(session_id)
                    
                    where_sql = " WHERE " + " AND ".join(where) if where else ""
                    
                    cur.execute(
                        f"SELECT {_MEMORY_COLUMNS} FROM core.memory{where_sql} ORDER BY created_at LIMIT %s OFFSET %s",
                        (*params, keep_count, 0),
                    )
                    all_memories = tuple(deserialize_memory(row) for row in cur.fetchall())
                    
                    if len(all_memories) <= keep_count:
                        return tuple()
                    
                    return all_memories[keep_count:]
                except psycopg.Error as ex:
                    raise MemoryPersistenceError("Failed to select excess memories.") from ex