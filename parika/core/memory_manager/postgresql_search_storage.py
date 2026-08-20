"""
PARIKA Memory Search Storage - PostgreSQL Implementation

PostgreSQL search and query operations for MemoryManager.
"""

from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from parika.core.memory_manager.exceptions import MemoryPersistenceError
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.postgresql_serialization import deserialize_memory, serialize_memory

MEMORY_COLUMNS: str = (
    "memory_id, kind, origin, content, created_at, updated_at, tags, metadata, "
    "scope, session_id, importance_score, access_count, last_accessed_at, "
    "decay_at, category, importance, confidence"
)


def _fts_quote_query(text: str) -> str:
    """Safely escape free-form text for use as a PostgreSQL tsquery."""
    tokens = [token for token in text.split() if token.strip()]
    if not tokens:
        return ""
    return " & ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _fts_quote_query_any(text: str) -> str:
    """Safely escape free-form text for use as a PostgreSQL tsquery, matching any token (OR)."""
    tokens = [token for token in text.split() if token.strip()]
    if not tokens:
        return ""
    return " | ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def search_candidates(
    connection,
    *,
    text: str,
    scope: str | None,
    session_id: str | None,
    kind: str | None,
    pool_size: int,
    category: str | None = None,
    require_all_terms: bool = False,
) -> tuple[tuple[Memory, float | None], ...]:
    """Retrieve a candidate pool for MemoryManager.search()."""
    query = _fts_quote_query_any(text) if not require_all_terms else _fts_quote_query(text)
    if not query:
        return ()

    clauses = ["m.search_vector @@ to_tsquery('simple', %s)"]
    params = [query]

    if scope is not None:
        clauses.append("m.scope = %s")
        params.append(scope)
    if session_id is not None:
        clauses.append("m.session_id = %s")
        params.append(session_id)
    if kind is not None:
        clauses.append("m.kind = %s")
        params.append(kind)
    if category is not None:
        clauses.append("m.category = %s")
        params.append(category)

    where_sql = " AND ".join(clauses)

    try:
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT m.*, ts_rank_cd(m.search_vector, to_tsquery('simple', %s)) AS rank
                FROM core.memory m
                WHERE {where_sql}
                ORDER BY rank
                LIMIT %s;
                """,
                (query, *params, pool_size),
            )
            rows = cur.fetchall()
            return tuple((deserialize_memory(row), float(row["rank"])) for row in rows)
    except psycopg.Error as ex:
        raise MemoryPersistenceError("Failed to search memories.") from ex


def get_by_scope(connection, *, scope: str, session_id: str | None) -> tuple[Memory, ...]:
    """Retrieve memories matching a scope (and optional session)."""
    clauses = ["m.scope = %s"]
    params = [scope]
    if session_id is not None:
        clauses.append("m.session_id = %s")
        params.append(session_id)

    where_sql = " AND ".join(clauses)

    try:
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {MEMORY_COLUMNS} FROM core.memory m WHERE {where_sql} ORDER BY m.created_at;",
                params,
            )
            return tuple(deserialize_memory(row) for row in cur.fetchall())
    except psycopg.Error as ex:
        raise MemoryPersistenceError("Failed to retrieve memories by scope.") from ex


def get_by_kind(connection, *, kind: str) -> tuple[Memory, ...]:
    """Retrieve memories matching a kind."""
    try:
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {MEMORY_COLUMNS} FROM core.memory m WHERE m.kind = %s ORDER BY m.created_at;",
                (kind,),
            )
            return tuple(deserialize_memory(row) for row in cur.fetchall())
    except psycopg.Error as ex:
        raise MemoryPersistenceError("Failed to retrieve memories by kind.") from ex


def get_by_category(connection, *, category: str) -> tuple[Memory, ...]:
    """Retrieve memories matching a category."""
    try:
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {MEMORY_COLUMNS} FROM core.memory m WHERE m.category = %s ORDER BY m.created_at;",
                (category,),
            )
            return tuple(deserialize_memory(row) for row in cur.fetchall())
    except psycopg.Error as ex:
        raise MemoryPersistenceError("Failed to retrieve memories by category.") from ex


def list_memories(
    connection,
    *,
    category: str | None,
    scope: str | None,
    session_id: str | None,
    limit: int | None,
) -> tuple[Memory, ...]:
    """Retrieve memories matching optional filters, newest-updated first."""
    clauses = ["1 = 1"]
    params = []

    if category is not None:
        clauses.append("m.category = %s")
        params.append(category)
    if scope is not None:
        clauses.append("m.scope = %s")
        params.append(scope)
    if session_id is not None:
        clauses.append("m.session_id = %s")
        params.append(session_id)

    where_sql = " AND ".join(clauses)
    limit_sql = f" LIMIT {limit}" if limit is not None else ""

    try:
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {MEMORY_COLUMNS} FROM core.memory m WHERE {where_sql} ORDER BY m.updated_at DESC{limit_sql};",
                params,
            )
            return tuple(deserialize_memory(row) for row in cur.fetchall())
    except psycopg.Error as ex:
        raise MemoryPersistenceError("Failed to list memories.") from ex


def delete_all(
    connection,
    *,
    category: str | None,
    scope: str | None,
    session_id: str | None,
) -> tuple[Memory, ...]:
    """Delete every memory matching optional filters; returns removed rows."""
    clauses = ["1 = 1"]
    params = []

    if category is not None:
        clauses.append("category = %s")
        params.append(category)
    if scope is not None:
        clauses.append("scope = %s")
        params.append(scope)
    if session_id is not None:
        clauses.append("session_id = %s")
        params.append(session_id)

    where_sql = " AND ".join(clauses)

    try:
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {MEMORY_COLUMNS} FROM core.memory WHERE {where_sql};",
                params,
            )
            removed = tuple(deserialize_memory(row) for row in cur.fetchall())

            cur.execute(f"DELETE FROM core.memory WHERE {where_sql};", params)
            connection.commit()
            return removed
    except psycopg.Error as ex:
        connection.rollback()
        raise MemoryPersistenceError("Failed to delete memories.") from ex


def count_by(connection, *, column: str) -> dict[str, int]:
    """Return a `{value: count}` breakdown for one column."""
    try:
        with connection.cursor() as cur:
            cur.execute(
                f"SELECT {column}, COUNT(*) FROM core.memory GROUP BY {column};"
            )
            return {str(row[0]): int(row[1]) for row in cur.fetchall()}
    except psycopg.Error as ex:
        raise MemoryPersistenceError("Failed to count memories by column.") from ex


def touch(connection, *, memory_id: str, accessed_at: datetime) -> Memory | None:
    """Bump access_count and last_accessed_at; return the updated Memory."""
    try:
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE core.memory
                SET access_count = access_count + 1, last_accessed_at = %s
                WHERE memory_id = %s
                RETURNING *;
                """,
                (accessed_at.isoformat(), memory_id),
            )
            row = cur.fetchone()
            connection.commit()
            return deserialize_memory(row) if row else None
    except psycopg.Error as ex:
        connection.rollback()
        raise MemoryPersistenceError("Failed to touch memory.") from ex


def select_expired(connection, *, now: datetime) -> tuple[Memory, ...]:
    """Read-only selection of memories whose decay_at has passed."""
    try:
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {MEMORY_COLUMNS} FROM core.memory WHERE decay_at IS NOT NULL AND decay_at <= %s;",
                (now.isoformat(),),
            )
            return tuple(deserialize_memory(row) for row in cur.fetchall())
    except psycopg.Error as ex:
        raise MemoryPersistenceError("Failed to select expired memories.") from ex


def select_excess(
    connection, *, scope: str | None, session_id: str | None, keep_count: int
) -> tuple[Memory, ...]:
    """Read-only selection of the least-valuable excess memories beyond `keep_count`."""
    clauses = ["1 = 1"]
    params = []

    if scope is not None:
        clauses.append("scope = %s")
        params.append(scope)
    if session_id is not None:
        clauses.append("session_id = %s")
        params.append(session_id)

    where_sql = " AND ".join(clauses)

    try:
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT {MEMORY_COLUMNS} FROM core.memory
                WHERE {where_sql}
                ORDER BY importance_score ASC, access_count ASC, last_accessed_at ASC NULLS FIRST
                LIMIT (SELECT GREATEST(COUNT(*) - %s, 0) FROM core.memory WHERE {where_sql});
                """,
                (*params, keep_count),
            )
            return tuple(deserialize_memory(row) for row in cur.fetchall())
    except psycopg.Error as ex:
        raise MemoryPersistenceError("Failed to select excess memories.") from ex


def select_stale(
    connection,
    *,
    scope: str,
    session_id: str | None,
    kind: str,
    older_than: datetime,
    max_access_count: int,
) -> tuple[Memory, ...]:
    """Read-only selection of consolidation candidates."""
    clauses = [
        "scope = %s",
        "kind = %s",
        "created_at <= %s",
        "access_count <= %s",
    ]
    params = [scope, kind, older_than.isoformat(), max_access_count]

    if session_id is not None:
        clauses.append("session_id = %s")
        params.append(session_id)

    where_sql = " AND ".join(clauses)

    try:
        with connection.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {MEMORY_COLUMNS} FROM core.memory WHERE {where_sql} ORDER BY created_at;",
                params,
            )
            return tuple(deserialize_memory(row) for row in cur.fetchall())
    except psycopg.Error as ex:
        raise MemoryPersistenceError("Failed to select stale memories.") from ex