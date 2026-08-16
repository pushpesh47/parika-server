"""
PARIKA Knowledge Unit Storage

SQLite-backed persistence and lexical (FTS5 BM25) search for extracted
Knowledge units, shared by every KnowledgeEngine implementation shipped
by this Module.

This lives outside `parika/core/knowledge_manager/` deliberately:
KnowledgeManager's storage contract (`KnowledgeStorage`) only covers
`KnowledgeSource` metadata -- extracted Knowledge units are each
engine's own responsibility to store and search (see
docs/architecture/Intelligence_Foundation_Design.md section 5.3).
"""

from __future__ import annotations

import json
import sqlite3

from datetime import UTC, datetime
from pathlib import Path, PurePath
from types import MappingProxyType
from uuid import UUID, uuid4

from parika.core.knowledge_manager.knowledge import Knowledge
from parika.core.knowledge_manager.search_result import SearchResult

SQLITE_BUSY_TIMEOUT_MS: int = 5000


def _fts5_quote_query(text: str) -> str:
    """
    Safely escape free-form text for use as an FTS5 `MATCH` query.

    Arbitrary text (a chat message used as a Context Assembly search
    query, a source file's content, ...) can contain characters
    FTS5's query-syntax parser treats specially (`.`, `-`, `:`, `(`,
    `)`, `"`, ...), which would otherwise raise
    `sqlite3.OperationalError: fts5: syntax error`. Wrapping each
    whitespace-separated token in double quotes makes every token a
    literal one-word phrase (punctuation inside a quoted phrase is
    inert to the parser), while still joining tokens with FTS5's
    default implicit AND -- identical retrieval semantics to an
    unquoted multi-term query, just syntax-error-proof. See the
    identical helper in
    `parika/core/memory_manager/search_storage.py`.
    """

    return " ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in text.split())


def _fts5_quote_query_any(text: str) -> str:
    """
    Safely escape free-form text for use as an FTS5 `MATCH` query,
    matching *any* token (explicit OR) rather than requiring every
    token to match.

    Used by `search()` for Context Assembly's automatic retrieval: a
    natural-language question like "What is the refund policy?"
    shares only "refund"/"policy" with indexed content like "Our
    refund policy allows returns within 30 days." -- requiring every
    token (including "what"/"is"/"the") to match would silently
    return zero candidates for exactly the kind of question Context
    Assembly exists to answer. OR-matching maximizes recall;
    `bm25()` ranking is what keeps precision -- still purely lexical,
    never semantic. See the identical helper/rationale in
    `parika/core/memory_manager/search_storage.py`.
    """

    tokens = [token for token in text.split() if token.strip()]

    if not tokens:
        return ""

    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


class KnowledgeUnitStorageError(Exception):
    """Raised when a knowledge unit storage operation fails."""


class KnowledgeUnitStorage:
    """
    Shared SQLite persistence + FTS5 search for extracted Knowledge
    units.
    """

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
                CREATE TABLE IF NOT EXISTS knowledge_units (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    location TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_units_source_id
                ON knowledge_units(source_id);

                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_units_fts USING fts5(
                    title, content, content='knowledge_units', content_rowid='rowid'
                );

                CREATE TRIGGER IF NOT EXISTS knowledge_units_ai
                AFTER INSERT ON knowledge_units BEGIN
                    INSERT INTO knowledge_units_fts(rowid, title, content)
                    VALUES (new.rowid, new.title, new.content);
                END;

                CREATE TRIGGER IF NOT EXISTS knowledge_units_ad
                AFTER DELETE ON knowledge_units BEGIN
                    INSERT INTO knowledge_units_fts(knowledge_units_fts, rowid, title, content)
                    VALUES ('delete', old.rowid, old.title, old.content);
                END;
                """
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
            raise KnowledgeUnitStorageError(
                "Failed to shut down knowledge unit storage."
            ) from ex
        finally:
            self._connection = None

    def replace_units_for_source(
        self, source_id: UUID, units: list[Knowledge]
    ) -> int:
        """
        Replace every stored unit for a source with a new set.

        Used by `KnowledgeEngine.index()` implementations: re-indexing a
        source discards its previous units and stores the freshly
        extracted ones. Returns the number of units stored.
        """

        connection = self._require_connection()

        try:
            connection.execute(
                "DELETE FROM knowledge_units WHERE source_id = ?;",
                (str(source_id),),
            )

            for unit in units:
                connection.execute(
                    """
                    INSERT INTO knowledge_units
                    (id, source_id, title, content, location, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        str(unit.id),
                        str(unit.source_id),
                        unit.title,
                        unit.content,
                        unit.location,
                        json.dumps(dict(unit.metadata), ensure_ascii=False),
                        unit.created_at.isoformat(),
                    ),
                )

            connection.commit()

            return len(units)

        except sqlite3.Error as ex:
            connection.rollback()
            raise KnowledgeUnitStorageError(
                "Failed to store knowledge units."
            ) from ex

    def delete_units_for_source(self, source_id: UUID) -> None:
        connection = self._require_connection()

        try:
            connection.execute(
                "DELETE FROM knowledge_units WHERE source_id = ?;",
                (str(source_id),),
            )
            connection.commit()

        except sqlite3.Error as ex:
            connection.rollback()
            raise KnowledgeUnitStorageError(
                "Failed to remove knowledge units."
            ) from ex

    def search(
        self, *, source_ids: frozenset[UUID], text: str, limit: int
    ) -> tuple[SearchResult, ...]:
        """
        Lexical (FTS5 BM25) search restricted to a set of source ids.
        """

        if not source_ids:
            return ()

        connection = self._require_connection()

        placeholders = ", ".join("?" for _ in source_ids)

        try:
            cursor = connection.execute(
                f"""
                SELECT u.id, u.source_id, u.title, u.content, u.location,
                       u.metadata, u.created_at, bm25(knowledge_units_fts) AS rank
                FROM knowledge_units_fts
                JOIN knowledge_units u ON u.rowid = knowledge_units_fts.rowid
                WHERE knowledge_units_fts MATCH ?
                  AND u.source_id IN ({placeholders})
                ORDER BY rank
                LIMIT ?;
                """,
                (_fts5_quote_query_any(text), *(str(sid) for sid in source_ids), limit),
            )

            return tuple(_row_to_result(row) for row in cursor.fetchall())

        except sqlite3.Error as ex:
            raise KnowledgeUnitStorageError(
                "Failed to search knowledge units."
            ) from ex

    def _require_connection(self) -> sqlite3.Connection:
        connection = self._connection

        if connection is None:
            raise KnowledgeUnitStorageError(
                "Knowledge unit storage has not been initialized."
            )

        return connection


def build_knowledge_unit(
    *, source_id: UUID, title: str, content: str, location: str,
    metadata: dict[str, object] | None = None,
) -> Knowledge:
    """Convenience constructor used by engine implementations."""

    return Knowledge(
        id=uuid4(),
        source_id=source_id,
        title=title,
        content=content,
        location=location,
        metadata=MappingProxyType(metadata or {}),
        created_at=datetime.now(UTC),
    )


def _row_to_result(row: sqlite3.Row) -> SearchResult:
    knowledge = Knowledge(
        id=UUID(row["id"]),
        source_id=UUID(row["source_id"]),
        title=row["title"],
        content=row["content"],
        location=row["location"],
        metadata=MappingProxyType(json.loads(row["metadata"])),
        created_at=datetime.fromisoformat(row["created_at"]),
    )

    bm25_rank = float(row["rank"])
    score = 1.0 / (1.0 + max(0.0, bm25_rank))

    return SearchResult(knowledge=knowledge, score=score)
