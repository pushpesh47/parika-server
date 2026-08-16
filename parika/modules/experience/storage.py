"""
PARIKA Experience Storage

SQLite persistence layer for the Experience Module, mirroring
MemoryStorage's exact schema/pragma/connection-lifecycle pattern for
consistency (see docs/architecture/Intelligence_Foundation_Design.md
section 6A).
"""

from __future__ import annotations

import json
import sqlite3

from datetime import datetime, UTC
from pathlib import Path, PurePath
from types import MappingProxyType

from .exceptions import ExperiencePersistenceError
from .experience import Experience
from .experience_outcome import ExperienceOutcome

SQLITE_SCHEMA_VERSION: int = 1
SQLITE_BUSY_TIMEOUT_MS: int = 5000

_COLUMNS: str = (
    "experience_id, capability_id, outcome, created_at, provider_id, "
    "model_id, tool_id, latency_ms, token_count, correction_of, "
    "user_correction, metadata"
)


class ExperienceStorage:
    """SQLite persistence for Experience records."""

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
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS experiences (
                    experience_id TEXT PRIMARY KEY,
                    capability_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    provider_id TEXT NULL,
                    model_id TEXT NULL,
                    tool_id TEXT NULL,
                    latency_ms REAL NULL,
                    token_count INTEGER NULL,
                    correction_of TEXT NULL,
                    user_correction TEXT NULL,
                    metadata TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_experiences_capability
                ON experiences(capability_id, provider_id, model_id);
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
        if self._connection is None:
            return

        try:
            self._connection.close()
        except sqlite3.Error as ex:
            raise ExperiencePersistenceError(
                "Failed to shut down experience storage."
            ) from ex
        finally:
            self._connection = None

    def insert(self, experience: Experience) -> Experience:
        connection = self._require_connection()

        try:
            connection.execute(
                f"INSERT INTO experiences ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                _serialize(experience),
            )
            connection.commit()
            return experience

        except sqlite3.Error as ex:
            connection.rollback()
            raise ExperiencePersistenceError(
                "Failed to insert experience."
            ) from ex

    def get(self, experience_id: str) -> Experience | None:
        connection = self._require_connection()

        try:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM experiences WHERE experience_id = ?;",
                (experience_id,),
            ).fetchone()

            return _deserialize(row) if row is not None else None

        except sqlite3.Error as ex:
            raise ExperiencePersistenceError(
                "Failed to retrieve experience."
            ) from ex

    def exists(self, experience_id: str) -> bool:
        connection = self._require_connection()

        try:
            cursor = connection.execute(
                "SELECT EXISTS(SELECT 1 FROM experiences WHERE experience_id = ?);",
                (experience_id,),
            )
            return bool(cursor.fetchone()[0])

        except sqlite3.Error as ex:
            raise ExperiencePersistenceError(
                "Failed to determine experience existence."
            ) from ex

    def get_all(self) -> tuple[Experience, ...]:
        connection = self._require_connection()

        try:
            cursor = connection.execute(
                f"SELECT {_COLUMNS} FROM experiences ORDER BY created_at;"
            )
            return tuple(_deserialize(row) for row in cursor.fetchall())

        except sqlite3.Error as ex:
            raise ExperiencePersistenceError(
                "Failed to retrieve experiences."
            ) from ex

    def get_by_capability(self, capability_id: str) -> tuple[Experience, ...]:
        connection = self._require_connection()

        try:
            cursor = connection.execute(
                f"SELECT {_COLUMNS} FROM experiences "
                "WHERE capability_id = ? ORDER BY created_at;",
                (capability_id,),
            )
            return tuple(_deserialize(row) for row in cursor.fetchall())

        except sqlite3.Error as ex:
            raise ExperiencePersistenceError(
                "Failed to retrieve experiences by capability."
            ) from ex

    def aggregate_outcome_rate(
        self,
        *,
        capability_id: str,
        provider_id: str | None,
        model_id: str | None,
    ) -> tuple[int, int]:
        """
        Return (success_count, total_count) for the given filters. Only
        SUCCESS/FAILURE/PARTIAL outcomes count toward the total;
        USER_CORRECTED rows are excluded (they describe a correction of
        a prior experience, not a fresh outcome).
        """

        connection = self._require_connection()

        filters = ["capability_id = ?"]
        params: list[object] = [capability_id]

        if provider_id is not None:
            filters.append("provider_id = ?")
            params.append(provider_id)

        if model_id is not None:
            filters.append("model_id = ?")
            params.append(model_id)

        filters.append("outcome != ?")
        params.append(ExperienceOutcome.USER_CORRECTED.value)

        where_sql = " AND ".join(filters)

        try:
            cursor = connection.execute(
                f"""
                SELECT
                    SUM(CASE WHEN outcome = ? THEN 1 ELSE 0 END) AS successes,
                    COUNT(*) AS total
                FROM experiences
                WHERE {where_sql};
                """,
                (ExperienceOutcome.SUCCESS.value, *params),
            )
            row = cursor.fetchone()

            successes = int(row["successes"] or 0)
            total = int(row["total"] or 0)

            return successes, total

        except sqlite3.Error as ex:
            raise ExperiencePersistenceError(
                "Failed to aggregate experience outcomes."
            ) from ex

    def _require_connection(self) -> sqlite3.Connection:
        connection = self._connection

        if connection is None:
            raise ExperiencePersistenceError(
                "Experience storage has not been initialized."
            )

        return connection


def _serialize(experience: Experience) -> tuple:
    return (
        experience.experience_id,
        experience.capability_id,
        experience.outcome.value,
        experience.created_at.isoformat(),
        experience.provider_id,
        experience.model_id,
        experience.tool_id,
        experience.latency_ms,
        experience.token_count,
        experience.correction_of,
        experience.user_correction,
        json.dumps(dict(experience.metadata), ensure_ascii=False),
    )


def _deserialize(row: sqlite3.Row) -> Experience:
    return Experience(
        experience_id=row["experience_id"],
        capability_id=row["capability_id"],
        outcome=ExperienceOutcome(row["outcome"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        provider_id=row["provider_id"],
        model_id=row["model_id"],
        tool_id=row["tool_id"],
        latency_ms=row["latency_ms"],
        token_count=row["token_count"],
        correction_of=row["correction_of"],
        user_correction=row["user_correction"],
        metadata=MappingProxyType(json.loads(row["metadata"])),
    )
