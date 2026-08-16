"""
PARIKA Memory Storage Migrations

Schema creation, verification, and additive migration for the
MemoryManager's SQLite database.

This module contains no business logic, no validation of Memory content,
and no CRUD operations -- only schema lifecycle management. Extracted
from storage.py to keep each file within the project's file-size
guideline.

Schema history
--------------
v1: `memories(memory_id, kind, origin, content, created_at, updated_at,
     tags, metadata)` + `idx_memories_kind`.
v2: adds `scope`, `session_id`, `importance_score`, `access_count`,
    `last_accessed_at`, `decay_at` columns; adds `idx_memories_scope`,
    `idx_memories_decay_at`; adds the `memories_fts` FTS5 external-content
    table with insert/update/delete sync triggers. No column removed, no
    existing row altered beyond receiving default values for new columns.
v3: adds `category`, `importance`, `confidence` columns; adds
    `idx_memories_category`. No column removed, no existing row altered
    beyond receiving default values for new columns.
"""

from __future__ import annotations

import sqlite3

from datetime import datetime

from parika.core.memory_manager.exceptions import MemoryPersistenceError

SQLITE_SCHEMA_VERSION: int = 3
SQLITE_BUSY_TIMEOUT_MS: int = 5000

_DEFAULT_SCOPE: str = "session"
_DEFAULT_CATEGORY: str = "custom"
_DEFAULT_IMPORTANCE: str = "normal"

_FTS_SCHEMA_SCRIPT: str = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, content='memories', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.rowid, old.content);
    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;
"""


def configure_database(connection: sqlite3.Connection) -> None:
    """
    Configure SQLite runtime settings.

    Raises
    ------
    MemoryPersistenceError
        If database configuration fails.
    """

    try:
        connection.execute("PRAGMA foreign_keys = ON;")
        connection.execute("PRAGMA journal_mode = WAL;")
        connection.execute("PRAGMA synchronous = NORMAL;")
        connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")

    except sqlite3.Error as ex:
        raise MemoryPersistenceError(
            "Failed to configure SQLite database."
        ) from ex


def initialize_schema(connection: sqlite3.Connection) -> None:
    """
    Create, migrate, and verify the memory database schema.

    Reads the current `PRAGMA user_version` and branches:
    - `0` (brand new database): creates the full current schema directly.
    - `1` (pre-existing v1 database): runs v1->v2, then v2->v3.
    - `2` (pre-existing v2 database): runs the additive v2->v3 migration.
    - `SQLITE_SCHEMA_VERSION` (already migrated): no-op.
    - anything else: raises, refusing to operate on an unrecognized
      schema version.

    Raises
    ------
    MemoryPersistenceError
        If schema creation, migration, or verification fails.
    """

    try:
        current_version = connection.execute(
            "PRAGMA user_version;"
        ).fetchone()[0]

        if current_version == 0:
            _create_v3_schema_fresh(connection)
        elif current_version == 1:
            _migrate_v1_to_v2(connection)
            _migrate_v2_to_v3(connection)
        elif current_version == 2:
            _migrate_v2_to_v3(connection)
        elif current_version == SQLITE_SCHEMA_VERSION:
            pass
        else:
            raise MemoryPersistenceError(
                "Unsupported memory database schema version."
            )

        connection.commit()

    except sqlite3.Error as ex:
        connection.rollback()

        raise MemoryPersistenceError(
            "Failed to initialize memory database schema."
        ) from ex

    _verify_schema(connection)


def _create_v3_schema_fresh(connection: sqlite3.Connection) -> None:
    """Create the full, current-version schema on a brand new database."""

    cursor = connection.cursor()

    cursor.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS metadata
        (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memories
        (
            memory_id         TEXT PRIMARY KEY,
            kind              TEXT NOT NULL,
            origin            TEXT NOT NULL,
            content           TEXT NOT NULL,
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL,
            tags              TEXT NOT NULL,
            metadata          TEXT NOT NULL,
            scope             TEXT NOT NULL DEFAULT 'session',
            session_id        TEXT NULL,
            importance_score  REAL NOT NULL DEFAULT 0.0,
            access_count      INTEGER NOT NULL DEFAULT 0,
            last_accessed_at  TEXT NULL,
            decay_at          TEXT NULL,
            category          TEXT NOT NULL DEFAULT '{_DEFAULT_CATEGORY}',
            importance        TEXT NOT NULL DEFAULT '{_DEFAULT_IMPORTANCE}',
            confidence        REAL NOT NULL DEFAULT 1.0
        );

        CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
        CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope, session_id);
        CREATE INDEX IF NOT EXISTS idx_memories_decay_at ON memories(decay_at);
        CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
        """
    )

    cursor.executescript(_FTS_SCHEMA_SCRIPT)

    connection.execute(
        """
        INSERT OR IGNORE INTO metadata (key, value)
        VALUES ('schema_version', ?), ('created_at', ?);
        """,
        (str(SQLITE_SCHEMA_VERSION), datetime.now().isoformat()),
    )

    connection.execute(f"PRAGMA user_version = {SQLITE_SCHEMA_VERSION};")


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    """
    Additively migrate a v1 database to v2.

    No existing column is dropped or renamed and no existing row's
    memory_id/kind/origin/content/created_at/updated_at/tags/metadata is
    modified; new columns receive safe, neutral defaults.
    """

    cursor = connection.cursor()

    existing_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(memories);")
    }

    if "scope" not in existing_columns:
        cursor.execute(
            f"ALTER TABLE memories ADD COLUMN scope TEXT NOT NULL DEFAULT '{_DEFAULT_SCOPE}';"
        )

    if "session_id" not in existing_columns:
        cursor.execute("ALTER TABLE memories ADD COLUMN session_id TEXT NULL;")

    if "importance_score" not in existing_columns:
        cursor.execute(
            "ALTER TABLE memories ADD COLUMN importance_score REAL NOT NULL DEFAULT 0.0;"
        )

    if "access_count" not in existing_columns:
        cursor.execute(
            "ALTER TABLE memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0;"
        )

    if "last_accessed_at" not in existing_columns:
        cursor.execute("ALTER TABLE memories ADD COLUMN last_accessed_at TEXT NULL;")

    if "decay_at" not in existing_columns:
        cursor.execute("ALTER TABLE memories ADD COLUMN decay_at TEXT NULL;")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope, session_id);"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_decay_at ON memories(decay_at);"
    )

    cursor.executescript(_FTS_SCHEMA_SCRIPT)

    # One-time backfill of the FTS index for rows that existed before the
    # FTS5 table did.
    cursor.execute(
        """
        INSERT INTO memories_fts(rowid, content)
        SELECT rowid, content FROM memories
        WHERE rowid NOT IN (SELECT rowid FROM memories_fts);
        """
    )

    connection.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?);",
        ("2",),
    )

    # Intermediate marker (v2, not the current SQLITE_SCHEMA_VERSION) --
    # initialize_schema() always runs _migrate_v2_to_v3() immediately
    # afterward when starting from v1, so the database is never left
    # marked as a version that doesn't match its actual columns.
    connection.execute("PRAGMA user_version = 2;")


def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    """
    Additively migrate a v2 database to v3.

    No existing column is dropped or renamed and no existing row's
    other columns are modified; new columns receive safe, neutral
    defaults (category='custom', importance='normal', confidence=1.0).
    """

    cursor = connection.cursor()

    existing_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(memories);")
    }

    if "category" not in existing_columns:
        cursor.execute(
            f"ALTER TABLE memories ADD COLUMN category TEXT NOT NULL DEFAULT '{_DEFAULT_CATEGORY}';"
        )

    if "importance" not in existing_columns:
        cursor.execute(
            f"ALTER TABLE memories ADD COLUMN importance TEXT NOT NULL DEFAULT '{_DEFAULT_IMPORTANCE}';"
        )

    if "confidence" not in existing_columns:
        cursor.execute(
            "ALTER TABLE memories ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0;"
        )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);"
    )

    connection.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?);",
        (str(SQLITE_SCHEMA_VERSION),),
    )

    connection.execute(f"PRAGMA user_version = {SQLITE_SCHEMA_VERSION};")


def _verify_schema(connection: sqlite3.Connection) -> None:
    """
    Verify the database schema version.

    Raises
    ------
    MemoryPersistenceError
        If the schema version is unsupported.
    """

    try:
        version: int = connection.execute("PRAGMA user_version;").fetchone()[0]

        if version != SQLITE_SCHEMA_VERSION:
            raise MemoryPersistenceError(
                "Unsupported memory database schema version."
            )

    except sqlite3.Error as ex:
        raise MemoryPersistenceError(
            "Failed to verify memory database schema."
        ) from ex
