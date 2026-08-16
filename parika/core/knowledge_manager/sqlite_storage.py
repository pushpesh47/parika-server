"""
PARIKA SQLite Knowledge Storage

Concrete SQLite implementation of the KnowledgeStorage contract,
persisting only KnowledgeSource metadata rows -- never extracted
Knowledge units, which remain the responsibility of the resolved
KnowledgeEngine (see docs/architecture/Intelligence_Foundation_Design.md
section 5.2).

This module contains no indexing, searching, or content-processing
logic -- only structural persistence of KnowledgeSource objects, the
same boundary MemoryStorage keeps for Memory objects.

Thread Safety
-------------
SqliteKnowledgeStorage is not thread-safe by itself; KnowledgeManager
does not currently provide its own lock (unlike MemoryManager), so
callers sharing one instance across threads are responsible for their
own synchronization.
"""

from __future__ import annotations

import json
import sqlite3

from datetime import UTC, datetime
from pathlib import Path, PurePath
from types import MappingProxyType
from uuid import UUID

from .exceptions import KnowledgeStorageError
from .knowledge_source import KnowledgeSource
from .source_kind import KnowledgeSourceKind
from .source_status import KnowledgeSourceStatus
from .storage import KnowledgeStorage

SQLITE_SCHEMA_VERSION: int = 1
SQLITE_BUSY_TIMEOUT_MS: int = 5000

_COLUMNS: str = (
    "id, name, kind, location, status, description, metadata, "
    "created_at, content_hash, last_indexed_at"
)


class SqliteKnowledgeStorage(KnowledgeStorage):
    """
    SQLite-backed persistence for KnowledgeSource objects.
    """

    __slots__ = ("_database_path", "_connection")

    def __init__(self, database_path: Path) -> None:
        if not isinstance(database_path, PurePath):
            raise TypeError("database_path must be a pathlib.Path object.")

        self._database_path: Path = database_path
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Open the connection, configure SQLite, and create the schema."""

        if self._connection is not None:
            return

        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)

            self._connection = sqlite3.connect(
                check_same_thread=False,
                database=self._database_path,
            )

            self._connection.row_factory = sqlite3.Row

            self._connection.execute("PRAGMA foreign_keys = ON;")
            self._connection.execute("PRAGMA journal_mode = WAL;")
            self._connection.execute("PRAGMA synchronous = NORMAL;")
            self._connection.execute(
                f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};"
            )

            self._connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    location TEXT NOT NULL,
                    status TEXT NOT NULL,
                    description TEXT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    content_hash TEXT NULL,
                    last_indexed_at TEXT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_sources_kind
                ON knowledge_sources(kind);

                CREATE INDEX IF NOT EXISTS idx_knowledge_sources_status
                ON knowledge_sources(status);
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
        """Close the active database connection."""

        if self._connection is None:
            return

        try:
            self._connection.close()
        except sqlite3.Error as ex:
            raise KnowledgeStorageError(
                "Failed to shut down knowledge source storage."
            ) from ex
        finally:
            self._connection = None

    def save(self, source: KnowledgeSource) -> None:
        connection = self._require_connection()

        try:
            connection.execute(
                f"INSERT INTO knowledge_sources ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                _serialize(source),
            )
            connection.commit()

        except sqlite3.Error as ex:
            connection.rollback()
            raise KnowledgeStorageError(
                "Failed to save knowledge source."
            ) from ex

    def update(self, source: KnowledgeSource) -> None:
        connection = self._require_connection()

        try:
            (
                source_id, name, kind, location, status, description,
                metadata, created_at, content_hash, last_indexed_at,
            ) = _serialize(source)

            connection.execute(
                """
                UPDATE knowledge_sources
                SET name = ?, kind = ?, location = ?, status = ?,
                    description = ?, metadata = ?, created_at = ?,
                    content_hash = ?, last_indexed_at = ?
                WHERE id = ?;
                """,
                (
                    name, kind, location, status, description, metadata,
                    created_at, content_hash, last_indexed_at, source_id,
                ),
            )
            connection.commit()

        except sqlite3.Error as ex:
            connection.rollback()
            raise KnowledgeStorageError(
                "Failed to update knowledge source."
            ) from ex

    def delete(self, source_id: UUID) -> None:
        connection = self._require_connection()

        try:
            connection.execute(
                "DELETE FROM knowledge_sources WHERE id = ?;", (str(source_id),)
            )
            connection.commit()

        except sqlite3.Error as ex:
            connection.rollback()
            raise KnowledgeStorageError(
                "Failed to delete knowledge source."
            ) from ex

    def get(self, source_id: UUID) -> KnowledgeSource:
        connection = self._require_connection()

        try:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM knowledge_sources WHERE id = ?;",
                (str(source_id),),
            ).fetchone()

        except sqlite3.Error as ex:
            raise KnowledgeStorageError(
                "Failed to retrieve knowledge source."
            ) from ex

        if row is None:
            raise KeyError(str(source_id))

        return _deserialize(row)

    def contains(self, source_id: UUID) -> bool:
        connection = self._require_connection()

        try:
            cursor = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM knowledge_sources WHERE id = ?);",
                (str(source_id),),
            )
            return bool(cursor.fetchone()[0])

        except sqlite3.Error as ex:
            raise KnowledgeStorageError(
                "Failed to determine knowledge source existence."
            ) from ex

    def get_all(self) -> tuple[KnowledgeSource, ...]:
        connection = self._require_connection()

        try:
            cursor = connection.execute(
                f"SELECT {_COLUMNS} FROM knowledge_sources ORDER BY created_at;"
            )
            return tuple(_deserialize(row) for row in cursor.fetchall())

        except sqlite3.Error as ex:
            raise KnowledgeStorageError(
                "Failed to retrieve knowledge sources."
            ) from ex

    def count(self) -> int:
        connection = self._require_connection()

        try:
            cursor = connection.execute("SELECT COUNT(*) FROM knowledge_sources;")
            return int(cursor.fetchone()[0])

        except sqlite3.Error as ex:
            raise KnowledgeStorageError(
                "Failed to count knowledge sources."
            ) from ex

    def get_many(self, source_ids: frozenset[UUID]) -> tuple[KnowledgeSource, ...]:
        if not source_ids:
            return ()

        connection = self._require_connection()

        placeholders = ", ".join("?" for _ in source_ids)

        try:
            cursor = connection.execute(
                f"SELECT {_COLUMNS} FROM knowledge_sources "
                f"WHERE id IN ({placeholders}) ORDER BY created_at;",
                tuple(str(source_id) for source_id in source_ids),
            )
            return tuple(_deserialize(row) for row in cursor.fetchall())

        except sqlite3.Error as ex:
            raise KnowledgeStorageError(
                "Failed to retrieve knowledge sources."
            ) from ex

    def _require_connection(self) -> sqlite3.Connection:
        connection = self._connection

        if connection is None:
            raise KnowledgeStorageError(
                "Knowledge source storage has not been initialized."
            )

        return connection


def _serialize(
    source: KnowledgeSource,
) -> tuple[str, str, str, str, str, str | None, str, str, str | None, str | None]:
    return (
        str(source.id),
        source.name,
        source.kind.value,
        source.location,
        source.status.value,
        source.description,
        json.dumps(dict(source.metadata), ensure_ascii=False, separators=(",", ":")),
        source.created_at.isoformat(),
        source.content_hash,
        source.last_indexed_at.isoformat() if source.last_indexed_at is not None else None,
    )


def _deserialize(row: sqlite3.Row) -> KnowledgeSource:
    return KnowledgeSource(
        id=UUID(row["id"]),
        name=row["name"],
        kind=KnowledgeSourceKind(row["kind"]),
        location=row["location"],
        status=KnowledgeSourceStatus(row["status"]),
        description=row["description"],
        metadata=MappingProxyType(json.loads(row["metadata"])),
        created_at=datetime.fromisoformat(row["created_at"]),
        content_hash=row["content_hash"],
        last_indexed_at=(
            datetime.fromisoformat(row["last_indexed_at"])
            if row["last_indexed_at"] is not None
            else None
        ),
    )
