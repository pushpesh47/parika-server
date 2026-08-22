"""
PARIKA Knowledge Unit Storage - PostgreSQL Implementation

PostgreSQL-backed persistence and lexical search for extracted
Knowledge units.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path, PurePath
from types import MappingProxyType
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from parika.core.knowledge_manager.knowledge import Knowledge
from parika.core.knowledge_manager.search_result import SearchResult


class KnowledgeUnitStorageError(Exception):
    """Raised when a knowledge unit storage operation fails."""


def _fts5_quote_query(text: str) -> str:
    """Safely escape free-form text for use as a PostgreSQL tsquery."""
    tokens = [token for token in text.split() if token.strip()]
    if not tokens:
        return ""
    return " & ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _fts5_quote_query_any(text: str) -> str:
    """Safely escape free-form text for OR matching."""
    tokens = [token for token in text.split() if token.strip()]
    if not tokens:
        return ""
    return " | ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


class PostgreSQLKnowledgeUnitStorage:
    """Shared PostgreSQL persistence + FTS search for extracted Knowledge units."""

    __slots__ = ("_pool",)

    def __init__(self, pool) -> None:
        self._pool = pool

    def initialize(self) -> None:
        """No-op: schema is managed by Alembic migrations."""
        pass

    def shutdown(self) -> None:
        """No-op: pool is managed by PoolManager."""
        pass

    def _require_connection(self):
        return self._pool.connection()

    def replace_units_for_source(
        self, source_id: UUID, units: list[Knowledge]
    ) -> int:
        """Replace every stored unit for a source with a new set."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "DELETE FROM coding.knowledge_unit WHERE source_id = %s",
                        (str(source_id),),
                    )

                    for unit in units:
                        cur.execute(
                            """
                            INSERT INTO coding.knowledge_unit
                            (id, source_id, title, content, location, metadata, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
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

                    conn.commit()
                    return len(units)
                except psycopg.Error as ex:
                    conn.rollback()
                    raise KnowledgeUnitStorageError("Failed to store knowledge units.") from ex

    def delete_units_for_source(self, source_id: UUID) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "DELETE FROM coding.knowledge_unit WHERE source_id = %s",
                        (str(source_id),),
                    )
                    conn.commit()
                except psycopg.Error as ex:
                    conn.rollback()
                    raise KnowledgeUnitStorageError("Failed to remove knowledge units.") from ex

    def search(
        self, *, source_ids: frozenset[UUID], text: str, limit: int
    ) -> tuple[SearchResult, ...]:
        """Lexical (PostgreSQL full-text search) search restricted to a set of source ids."""
        if not source_ids:
            return ()

        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                placeholders = ", ".join(["%s"] * len(source_ids))

                try:
                    query = _fts5_quote_query_any(text)

                    if not query:
                        return ()

                    cur.execute(
                        f"""
                        SELECT u.id, u.source_id, u.title, u.content, u.location,
                               u.metadata, u.created_at,
                               ts_rank_cd(u.search_vector, to_tsquery('simple', %s)) AS rank
                        FROM coding.knowledge_unit u
                        WHERE u.search_vector @@ to_tsquery('simple', %s)
                          AND u.source_id IN ({placeholders})
                        ORDER BY rank
                        LIMIT %s;
                        """,
                        (query, query, *(str(sid) for sid in source_ids), limit),
                    )

                    return tuple(self._row_to_result(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise KnowledgeUnitStorageError("Failed to search knowledge units.") from ex

    def _row_to_result(self, row: dict) -> SearchResult:
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        
        created_at = row["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        
        knowledge = Knowledge(
            id=UUID(row["id"]),
            source_id=UUID(row["source_id"]),
            title=row["title"],
            content=row["content"],
            location=row["location"],
            metadata=MappingProxyType(metadata),
            created_at=created_at,
        )

        bm25_rank = float(row["rank"])
        score = 1.0 / (1.0 + max(0.0, bm25_rank))

        return SearchResult(knowledge=knowledge, score=score)


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