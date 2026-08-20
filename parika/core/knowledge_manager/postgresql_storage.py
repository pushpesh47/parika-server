"""
PARIKA Knowledge Storage - PostgreSQL Implementation

PostgreSQL persistence for KnowledgeSource objects.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path, PurePath
from types import MappingProxyType
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .exceptions import KnowledgeStorageError
from .knowledge_source import KnowledgeSource
from .source_kind import KnowledgeSourceKind
from .source_status import KnowledgeSourceStatus
from .storage import KnowledgeStorage


class PostgreSQLKnowledgeStorage(KnowledgeStorage):
    """PostgreSQL-backed persistence for KnowledgeSource objects."""

    __slots__ = ("_pool",)

    SQLITE_SCHEMA_VERSION: int = 1
    SQLITE_BUSY_TIMEOUT_MS: int = 5000

    _COLUMNS: str = (
        "id, name, kind, location, status, description, metadata, "
        "created_at, content_hash, last_indexed_at"
    )

    def __init__(self, pool) -> None:
        if not isinstance(pool, (str, Path, PurePath)):
            # It's a connection pool
            self._pool = pool
        else:
            raise TypeError("pool must be a psycopg_pool.ConnectionPool instance")

    def initialize(self) -> None:
        """No-op: schema is managed by Alembic migrations."""
        pass

    def shutdown(self) -> None:
        """No-op: pool is managed by PoolManager."""
        pass

    def _require_connection(self):
        return self._pool.connection()

    def save(self, source: KnowledgeSource) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        f"INSERT INTO core.knowledge_source ({self._COLUMNS}) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        self._serialize(source),
                    )
                    conn.commit()
                except psycopg.Error as ex:
                    conn.rollback()
                    raise KnowledgeStorageError("Failed to save knowledge source.") from ex

    def update(self, source: KnowledgeSource) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    (
                        source_id, name, kind, location, status, description,
                        metadata, created_at, content_hash, last_indexed_at,
                    ) = self._serialize(source)

                    cur.execute(
                        """
                        UPDATE core.knowledge_source
                        SET name = %s, kind = %s, location = %s, status = %s,
                            description = %s, metadata = %s, created_at = %s,
                            content_hash = %s, last_indexed_at = %s
                        WHERE id = %s
                        """,
                        (
                            name, kind, location, status, description, metadata,
                            created_at, content_hash, last_indexed_at, source_id,
                        ),
                    )
                    conn.commit()
                except psycopg.Error as ex:
                    conn.rollback()
                    raise KnowledgeStorageError("Failed to update knowledge source.") from ex

    def delete(self, source_id: UUID) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "DELETE FROM core.knowledge_source WHERE id = %s",
                        (str(source_id),)
                    )
                    conn.commit()
                except psycopg.Error as ex:
                    conn.rollback()
                    raise KnowledgeStorageError("Failed to delete knowledge source.") from ex

    def get(self, source_id: UUID) -> KnowledgeSource:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        f"SELECT {self._COLUMNS} FROM core.knowledge_source WHERE id = %s",
                        (str(source_id),)
                    )
                    row = cur.fetchone()
                    if row is None:
                        raise KeyError(str(source_id))
                    return self._deserialize(row)
                except psycopg.Error as ex:
                    raise KnowledgeStorageError("Failed to retrieve knowledge source.") from ex

    def contains(self, source_id: UUID) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "SELECT EXISTS(SELECT 1 FROM core.knowledge_source WHERE id = %s)",
                        (str(source_id),)
                    )
                    return bool(cur.fetchone()[0])
                except psycopg.Error as ex:
                    raise KnowledgeStorageError("Failed to determine knowledge source existence.") from ex

    def get_all(self) -> tuple[KnowledgeSource, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        f"SELECT {self._COLUMNS} FROM core.knowledge_source ORDER BY created_at"
                    )
                    return tuple(self._deserialize(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise KnowledgeStorageError("Failed to retrieve knowledge sources.") from ex

    def count(self) -> int:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("SELECT COUNT(*) FROM core.knowledge_source")
                    return int(cur.fetchone()[0])
                except psycopg.Error as ex:
                    raise KnowledgeStorageError("Failed to count knowledge sources.") from ex

    def get_many(self, source_ids: frozenset[UUID]) -> tuple[KnowledgeSource, ...]:
        if not source_ids:
            return ()

        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                placeholders = ", ".join(["%s"] * len(source_ids))
                try:
                    cur.execute(
                        f"SELECT {self._COLUMNS} FROM core.knowledge_source "
                        f"WHERE id IN ({placeholders}) ORDER BY created_at",
                        tuple(str(sid) for sid in source_ids)
                    )
                    return tuple(self._deserialize(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise KnowledgeStorageError("Failed to retrieve knowledge sources.") from ex

    def _serialize(
        self,
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

    def _deserialize(self, row: dict) -> KnowledgeSource:
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return KnowledgeSource(
            id=UUID(row["id"]),
            name=row["name"],
            kind=KnowledgeSourceKind(row["kind"]),
            location=row["location"],
            status=KnowledgeSourceStatus(row["status"]),
            description=row["description"],
            metadata=MappingProxyType(metadata),
            created_at=row["created_at"],
            content_hash=row["content_hash"],
            last_indexed_at=(
                row["last_indexed_at"]
                if row["last_indexed_at"] is not None
                else None
            ),
        )