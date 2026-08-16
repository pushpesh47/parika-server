"""
PARIKA Memory Search Storage

SQL query functions supporting MemoryManager's search, scoped retrieval,
lifecycle bookkeeping (touch), and consolidation/pruning selection.

Extracted from storage.py to keep each file within the project's
file-size guideline (see PARIKA_Core_Coding_Standards.md). Every
function here takes an already-open `sqlite3.Connection` explicitly
rather than `self`, so `MemoryStorage` (storage.py) remains the single
public class/entry point for this package's persistence layer -- these
are its private implementation detail, split into a separate file, not
a second public API surface.

This module performs no business logic and no content interpretation:
every function is a structural SQL query over already-stored values.
"""

from __future__ import annotations

import sqlite3

from datetime import datetime

from parika.core.memory_manager.exceptions import MemoryPersistenceError
from parika.core.memory_manager.memory import Memory
from parika.core.memory_manager.serialization import deserialize_memory

_MEMORY_COLUMN_NAMES: tuple[str, ...] = (
    "memory_id",
    "kind",
    "origin",
    "content",
    "created_at",
    "updated_at",
    "tags",
    "metadata",
    "scope",
    "session_id",
    "importance_score",
    "access_count",
    "last_accessed_at",
    "decay_at",
    "category",
    "importance",
    "confidence",
)

MEMORY_COLUMNS: str = ", ".join(_MEMORY_COLUMN_NAMES)


def _fts5_quote_token(token: str) -> str:
    """Escape one token as a literal, punctuation-safe FTS5 phrase."""

    return f'"{token.replace(chr(34), chr(34) * 2)}"'


def _fts5_quote_query(text: str) -> str:
    """
    Safely escape free-form text for use as an FTS5 `MATCH` query,
    requiring every token to match (implicit AND).

    Arbitrary user-supplied content (e.g. `remember()`'s duplicate-
    detection search, which searches on the caller's own raw
    content) can contain characters FTS5's query-syntax parser
    treats specially (`.`, `-`, `:`, `(`, `)`, `"`, ...), which would
    otherwise raise `sqlite3.OperationalError: fts5: syntax error`.
    Wrapping each whitespace-separated token in double quotes makes
    every token a literal one-word phrase (punctuation inside a
    quoted phrase is inert to the parser), while still joining tokens
    with FTS5's default implicit AND -- identical retrieval semantics
    to an unquoted multi-term query, just syntax-error-proof.
    """

    return " ".join(_fts5_quote_token(token) for token in text.split())


def _fts5_quote_query_any(text: str) -> str:
    """
    Safely escape free-form text for use as an FTS5 `MATCH` query,
    matching *any* token (explicit OR) rather than requiring every
    token to match.

    Used only for Context Assembly's automatic retrieval (see
    `MemoryManager.search()`/`remember()`'s duplicate check): a
    natural-language question like "What is my name?" shares only the
    single content word "name" with a stored memory like "The user's
    name is Pushpesh." -- requiring every token (including "what"/
    "is"/"my") to match would silently return zero candidates for
    exactly the kind of question Context Assembly exists to answer.
    OR-matching maximizes recall; `bm25()` ranking plus the existing
    recency/importance/frequency blend (see `retrieval.py`) is what
    keeps precision, exactly as it already does for every other
    scoring signal -- this is still purely lexical, never semantic.
    """

    tokens = [token for token in text.split() if token.strip()]

    if not tokens:
        return ""

    return " OR ".join(_fts5_quote_token(token) for token in tokens)


def get_by_scope(
    connection: sqlite3.Connection, *, scope: str, session_id: str | None
) -> tuple[Memory, ...]:
    """Retrieve memories matching a scope (and optional session)."""

    try:
        if session_id is None:
            cursor = connection.execute(
                f"SELECT {MEMORY_COLUMNS} FROM memories "
                "WHERE scope = ? ORDER BY created_at;",
                (scope,),
            )
        else:
            cursor = connection.execute(
                f"SELECT {MEMORY_COLUMNS} FROM memories "
                "WHERE scope = ? AND session_id = ? ORDER BY created_at;",
                (scope, session_id),
            )

        return tuple(deserialize_memory(row) for row in cursor.fetchall())

    except sqlite3.Error as ex:
        raise MemoryPersistenceError(
            "Failed to retrieve memories by scope."
        ) from ex


def get_by_kind(connection: sqlite3.Connection, *, kind: str) -> tuple[Memory, ...]:
    """Retrieve memories matching a kind."""

    try:
        cursor = connection.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories "
            "WHERE kind = ? ORDER BY created_at;",
            (kind,),
        )

        return tuple(deserialize_memory(row) for row in cursor.fetchall())

    except sqlite3.Error as ex:
        raise MemoryPersistenceError(
            "Failed to retrieve memories by kind."
        ) from ex


def get_by_category(
    connection: sqlite3.Connection, *, category: str
) -> tuple[Memory, ...]:
    """Retrieve memories matching a category."""

    try:
        cursor = connection.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories "
            "WHERE category = ? ORDER BY created_at;",
            (category,),
        )

        return tuple(deserialize_memory(row) for row in cursor.fetchall())

    except sqlite3.Error as ex:
        raise MemoryPersistenceError(
            "Failed to retrieve memories by category."
        ) from ex


def list_memories(
    connection: sqlite3.Connection,
    *,
    category: str | None,
    scope: str | None,
    session_id: str | None,
    limit: int | None,
) -> tuple[Memory, ...]:
    """
    Retrieve memories matching optional category/scope/session
    filters, newest-updated first, optionally capped by `limit`.
    """

    filters: list[str] = []
    params: list[object] = []

    if category is not None:
        filters.append("category = ?")
        params.append(category)

    if scope is not None:
        filters.append("scope = ?")
        params.append(scope)

    if session_id is not None:
        filters.append("session_id = ?")
        params.append(session_id)

    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    limit_sql = "LIMIT ?" if limit is not None else ""

    try:
        cursor = connection.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories {where_sql} "
            f"ORDER BY updated_at DESC {limit_sql};",
            (*params, *((limit,) if limit is not None else ())),
        )

        return tuple(deserialize_memory(row) for row in cursor.fetchall())

    except sqlite3.Error as ex:
        raise MemoryPersistenceError("Failed to list memories.") from ex


def delete_all(
    connection: sqlite3.Connection,
    *,
    category: str | None,
    scope: str | None,
    session_id: str | None,
) -> tuple[Memory, ...]:
    """
    Delete every memory matching optional category/scope/session
    filters (no filters = every memory), returning the removed rows.
    """

    removed = list_memories(
        connection, category=category, scope=scope, session_id=session_id, limit=None
    )

    if not removed:
        return ()

    filters: list[str] = []
    params: list[object] = []

    if category is not None:
        filters.append("category = ?")
        params.append(category)

    if scope is not None:
        filters.append("scope = ?")
        params.append(scope)

    if session_id is not None:
        filters.append("session_id = ?")
        params.append(session_id)

    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""

    try:
        connection.execute(f"DELETE FROM memories {where_sql};", tuple(params))
        connection.commit()

        return removed

    except sqlite3.Error as ex:
        connection.rollback()
        raise MemoryPersistenceError("Failed to clear memories.") from ex


def count_by(
    connection: sqlite3.Connection, *, column: str
) -> dict[str, int]:
    """Return a `{value: count}` breakdown for one column (category/importance/scope)."""

    if column not in {"category", "importance", "scope"}:
        raise MemoryPersistenceError(f"Cannot aggregate by column '{column}'.")

    try:
        cursor = connection.execute(
            f"SELECT {column} AS value, COUNT(*) AS total FROM memories "
            f"GROUP BY {column};"
        )

        return {row["value"]: int(row["total"]) for row in cursor.fetchall()}

    except sqlite3.Error as ex:
        raise MemoryPersistenceError(
            f"Failed to aggregate memories by '{column}'."
        ) from ex


def touch(
    connection: sqlite3.Connection, *, memory_id: str, accessed_at: datetime
) -> Memory | None:
    """Bump access_count and last_accessed_at; return the updated Memory."""

    try:
        cursor = connection.execute(
            """
            UPDATE memories
            SET access_count = access_count + 1, last_accessed_at = ?
            WHERE memory_id = ?;
            """,
            (accessed_at.isoformat(), memory_id),
        )
        connection.commit()

        if cursor.rowcount == 0:
            return None

        row = connection.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories WHERE memory_id = ?;",
            (memory_id,),
        ).fetchone()

        return deserialize_memory(row) if row is not None else None

    except sqlite3.Error as ex:
        connection.rollback()
        raise MemoryPersistenceError("Failed to touch memory.") from ex


def search_candidates(
    connection: sqlite3.Connection,
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
    Retrieve a candidate pool for MemoryManager.search().

    When `text` is non-empty, matches lexically via the `memories_fts`
    FTS5 table and returns each candidate's `bm25()` rank (lower is
    better, per SQLite's convention; final "higher is better"
    conversion happens in retrieval.py). When `text` is empty, returns
    filtered candidates with a `None` rank.

    `require_all_terms` controls FTS5 term matching:
    - False (the default; used by `MemoryManager.search()`, including
      Context Assembly's automatic retrieval): any query term may
      match (OR) -- maximizes recall for natural-language questions
      that share only one or two words with a stored memory (e.g.
      "What is my name?" against "The user's name is Pushpesh.");
      `bm25()` ranking plus `retrieval.py`'s recency/importance/
      frequency blend is what keeps precision.
    - True (used only by `remember()`'s duplicate-detection candidate
      search): every query term must match (AND) -- deliberately
      higher-precision, since a too-broad candidate pool here would
      let unrelated-but-lexically-overlapping memories (e.g. "distinct
      fact number 0" vs "distinct fact number 1") reach the
      `difflib`-based similarity check and be incorrectly merged.
    """

    filters: list[str] = []
    params: list[object] = []

    if scope is not None:
        filters.append("m.scope = ?")
        params.append(scope)

    if session_id is not None:
        filters.append("m.session_id = ?")
        params.append(session_id)

    if kind is not None:
        filters.append("m.kind = ?")
        params.append(kind)

    if category is not None:
        filters.append("m.category = ?")
        params.append(category)

    filter_sql = (" AND " + " AND ".join(filters)) if filters else ""

    try:
        if text.strip():
            qualified_columns = ", ".join(f"m.{name}" for name in _MEMORY_COLUMN_NAMES)
            match_query = (
                _fts5_quote_query(text) if require_all_terms else _fts5_quote_query_any(text)
            )

            cursor = connection.execute(
                f"""
                SELECT {qualified_columns}, bm25(memories_fts) AS rank
                FROM memories_fts
                JOIN memories m ON m.rowid = memories_fts.rowid
                WHERE memories_fts MATCH ?{filter_sql}
                ORDER BY rank
                LIMIT ?;
                """,
                (match_query, *params, pool_size),
            )

            return tuple(
                (deserialize_memory(row), float(row["rank"]))
                for row in cursor.fetchall()
            )

        where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""

        cursor = connection.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories m {where_sql} "
            "ORDER BY m.updated_at DESC LIMIT ?;",
            (*params, pool_size),
        )

        return tuple((deserialize_memory(row), None) for row in cursor.fetchall())

    except sqlite3.Error as ex:
        raise MemoryPersistenceError("Failed to search memories.") from ex


def select_stale(
    connection: sqlite3.Connection,
    *,
    scope: str,
    session_id: str | None,
    kind: str,
    older_than: datetime,
    max_access_count: int,
) -> tuple[Memory, ...]:
    """Read-only selection of consolidation candidates."""

    try:
        if session_id is None:
            cursor = connection.execute(
                f"SELECT {MEMORY_COLUMNS} FROM memories "
                "WHERE scope = ? AND kind = ? AND updated_at <= ? "
                "AND access_count <= ? ORDER BY updated_at;",
                (scope, kind, older_than.isoformat(), max_access_count),
            )
        else:
            cursor = connection.execute(
                f"SELECT {MEMORY_COLUMNS} FROM memories "
                "WHERE scope = ? AND session_id = ? AND kind = ? "
                "AND updated_at <= ? AND access_count <= ? "
                "ORDER BY updated_at;",
                (scope, session_id, kind, older_than.isoformat(), max_access_count),
            )

        return tuple(deserialize_memory(row) for row in cursor.fetchall())

    except sqlite3.Error as ex:
        raise MemoryPersistenceError(
            "Failed to select consolidation candidates."
        ) from ex


def select_expired(connection: sqlite3.Connection, *, now: datetime) -> tuple[Memory, ...]:
    """Read-only selection of memories whose decay_at has passed."""

    try:
        cursor = connection.execute(
            f"SELECT {MEMORY_COLUMNS} FROM memories "
            "WHERE decay_at IS NOT NULL AND decay_at <= ?;",
            (now.isoformat(),),
        )

        return tuple(deserialize_memory(row) for row in cursor.fetchall())

    except sqlite3.Error as ex:
        raise MemoryPersistenceError(
            "Failed to select expired memories."
        ) from ex


def select_excess(
    connection: sqlite3.Connection,
    *,
    scope: str | None,
    session_id: str | None,
    keep_count: int,
) -> tuple[Memory, ...]:
    """
    Read-only selection of the memories beyond the top `keep_count`
    most valuable (highest importance, most recently accessed) within a
    scope/session -- i.e. the least-valuable excess.
    """

    filters: list[str] = []
    params: list[object] = []

    if scope is not None:
        filters.append("scope = ?")
        params.append(scope)

    if session_id is not None:
        filters.append("session_id = ?")
        params.append(session_id)

    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""

    try:
        cursor = connection.execute(
            f"""
            SELECT {MEMORY_COLUMNS} FROM memories {where_sql}
            ORDER BY importance_score DESC,
                     COALESCE(last_accessed_at, created_at) DESC
            LIMIT -1 OFFSET ?;
            """,
            (*params, keep_count),
        )

        return tuple(deserialize_memory(row) for row in cursor.fetchall())

    except sqlite3.Error as ex:
        raise MemoryPersistenceError(
            "Failed to select excess memories."
        ) from ex
