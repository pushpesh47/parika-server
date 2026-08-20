"""
PARIKA Experience Storage - PostgreSQL Implementation

PostgreSQL persistence layer for the Experience Module.
"""

from __future__ import annotations

import json
from datetime import datetime, UTC
from types import MappingProxyType
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from .exceptions import ExperiencePersistenceError
from .experience import Experience
from .experience_outcome import ExperienceOutcome


class PostgreSQLExperienceStorage:
    """PostgreSQL persistence for Experience records."""

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

    def insert(self, experience: Experience) -> Experience:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO core.experience 
                        (experience_id, capability_id, outcome, created_at, provider_id, model_id, 
                         tool_id, latency_ms, token_count, correction_of, user_correction, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            experience.experience_id,
                            experience.capability_id,
                            experience.outcome.value,
                            experience.created_at,
                            experience.provider_id,
                            experience.model_id,
                            experience.tool_id,
                            experience.latency_ms,
                            experience.token_count,
                            experience.correction_of,
                            experience.user_correction,
                            json.dumps(dict(experience.metadata), ensure_ascii=False),
                        ),
                    )
                    conn.commit()
                    return experience
                except psycopg.Error as ex:
                    conn.rollback()
                    raise ExperiencePersistenceError("Failed to insert experience.") from ex

    def get(self, experience_id: str) -> Experience | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        """
                        SELECT experience_id, capability_id, outcome, created_at, provider_id, model_id,
                               tool_id, latency_ms, token_count, correction_of, user_correction, metadata
                        FROM core.experience
                        WHERE experience_id = %s
                        """,
                        (experience_id,),
                    )
                    row = cur.fetchone()
                    return self._deserialize(row) if row else None
                except psycopg.Error as ex:
                    raise ExperiencePersistenceError("Failed to retrieve experience.") from ex

    def exists(self, experience_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "SELECT EXISTS(SELECT 1 FROM core.experience WHERE experience_id = %s)",
                        (experience_id,),
                    )
                    return bool(cur.fetchone()[0])
                except psycopg.Error as ex:
                    raise ExperiencePersistenceError("Failed to determine experience existence.") from ex

    def get_all(self) -> tuple[Experience, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        """
                        SELECT experience_id, capability_id, outcome, created_at, provider_id, model_id,
                               tool_id, latency_ms, token_count, correction_of, user_correction, metadata
                        FROM core.experience
                        ORDER BY created_at
                        """
                    )
                    return tuple(self._deserialize(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise ExperiencePersistenceError("Failed to retrieve experiences.") from ex

    def get_by_capability(self, capability_id: str) -> tuple[Experience, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        """
                        SELECT experience_id, capability_id, outcome, created_at, provider_id, model_id,
                               tool_id, latency_ms, token_count, correction_of, user_correction, metadata
                        FROM core.experience
                        WHERE capability_id = %s
                        ORDER BY created_at
                        """,
                        (capability_id,),
                    )
                    return tuple(self._deserialize(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise ExperiencePersistenceError("Failed to retrieve experiences by capability.") from ex

    def aggregate_outcome_rate(
        self,
        *,
        capability_id: str,
        provider_id: str | None,
        model_id: str | None,
    ) -> tuple[int, int]:
        """
        Return (success_count, total_count) for the given filters.
        Only SUCCESS/FAILURE/PARTIAL outcomes count toward the total;
        USER_CORRECTED rows are excluded.
        """
        filters = ["capability_id = %s"]
        params = [capability_id]

        if provider_id is not None:
            filters.append("provider_id = %s")
            params.append(provider_id)

        if model_id is not None:
            filters.append("model_id = %s")
            params.append(model_id)

        filters.append("outcome != %s")
        params.append(ExperienceOutcome.USER_CORRECTED.value)

        where_sql = " AND ".join(filters)

        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        f"""
                        SELECT
                            SUM(CASE WHEN outcome = %s THEN 1 ELSE 0 END) AS successes,
                            COUNT(*) AS total
                        FROM core.experience
                        WHERE {where_sql}
                        """,
                        (ExperienceOutcome.SUCCESS.value, *params),
                    )
                    row = cur.fetchone()
                    successes = int(row[0] or 0)
                    total = int(row[1] or 0)
                    return successes, total
                except psycopg.Error as ex:
                    raise ExperiencePersistenceError("Failed to aggregate experience outcomes.") from ex

    def _deserialize(self, row: dict) -> Experience:
        return Experience(
            experience_id=row["experience_id"],
            capability_id=row["capability_id"],
            outcome=ExperienceOutcome(row["outcome"]),
            created_at=row["created_at"],
            provider_id=row["provider_id"],
            model_id=row["model_id"],
            tool_id=row["tool_id"],
            latency_ms=row["latency_ms"],
            token_count=row["token_count"],
            correction_of=row["correction_of"],
            user_correction=row["user_correction"],
            metadata=MappingProxyType(json.loads(row["metadata"])),
        )


# Keep the original ExperienceStorage as SQLite implementation
# This file replaces the module when PostgreSQL is used