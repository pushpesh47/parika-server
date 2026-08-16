"""
PARIKA Interfaces - Session Store

SQLite-backed persistence for session-wise chat history, replacing the
purely in-memory model `InterfaceSession` used before this milestone.

Lives in the Interfaces layer (not Core) -- session persistence is a
CLI/Interface-level concern, matching Dependency Rules ("Interfaces
communicate only with Core"). Uses the same SQLite pragma/schema-
version/FTS5 pattern already established by `MemoryStorage` and
`ExperienceStorage`, for consistency (see
docs/architecture/Intelligence_Foundation_Design.md section 8).
"""

from __future__ import annotations

import json
import sqlite3
import threading

from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path, PurePath
from uuid import uuid4

SQLITE_SCHEMA_VERSION: int = 1
SQLITE_BUSY_TIMEOUT_MS: int = 5000


def _fts5_quote_query(text: str) -> str:
    """
    Safely escape free-form text for use as an FTS5 `MATCH` query. See
    the identical helper in
    `parika/core/memory_manager/search_storage.py` for the full
    rationale (arbitrary punctuation would otherwise raise
    `sqlite3.OperationalError: fts5: syntax error`).
    """

    return " ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in text.split())


class SessionStoreError(Exception):
    """Base exception for session store errors."""


class SessionNotFoundError(SessionStoreError):
    """Raised when a requested session cannot be found."""


class SessionPersistenceError(SessionStoreError):
    """Raised when a session cannot be persisted or restored."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionSummary:
    """Immutable metadata describing one stored session."""

    session_id: str
    title: str | None
    summary: str | None
    workspace_path: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionMessage:
    """Immutable record of one stored session message."""

    session_id: str
    role: str
    content: str
    created_at: datetime
    token_count: int | None = None


class SqliteSessionStore:
    """SQLite-backed persistence for sessions and their messages."""

    __slots__ = ("_database_path", "_connection", "_lock")

    def __init__(self, database_path: Path) -> None:
        if not isinstance(database_path, PurePath):
            raise TypeError("database_path must be a pathlib.Path object.")

        self._database_path: Path = database_path
        self._connection: sqlite3.Connection | None = None
        self._lock: threading.Lock = threading.Lock()

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
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NULL,
                    summary TEXT NULL,
                    workspace_path TEXT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS session_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    token_count INTEGER NULL
                );

                CREATE INDEX IF NOT EXISTS idx_session_messages_session_id
                ON session_messages(session_id);

                CREATE VIRTUAL TABLE IF NOT EXISTS session_messages_fts USING fts5(
                    content, content='session_messages', content_rowid='id'
                );

                CREATE TRIGGER IF NOT EXISTS session_messages_ai
                AFTER INSERT ON session_messages BEGIN
                    INSERT INTO session_messages_fts(rowid, content)
                    VALUES (new.id, new.content);
                END;
                """
            )
            self._connection.execute(f"PRAGMA user_version = {SQLITE_SCHEMA_VERSION};")
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

        with self._lock:
            try:
                self._connection.close()
            except sqlite3.Error as ex:
                raise SessionPersistenceError(
                    "Failed to shut down session store."
                ) from ex
            finally:
                self._connection = None

    def ensure_session(
        self, session_id: str, *, workspace_path: str | None = None
    ) -> None:
        """Create a session row if it does not already exist. Idempotent."""

        with self._lock:
            connection = self._require_connection()
            now = datetime.now(UTC).isoformat()

            try:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO sessions
                    (session_id, workspace_path, created_at, updated_at, message_count)
                    VALUES (?, ?, ?, ?, 0);
                    """,
                    (session_id, workspace_path, now, now),
                )
                connection.commit()

            except sqlite3.Error as ex:
                connection.rollback()
                raise SessionPersistenceError("Failed to create session.") from ex

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        token_count: int | None = None,
    ) -> None:
        """
        Persist one message and bump the owning session's message_count
        and updated_at. Auto-creates the session row if it does not
        already exist.
        """

        with self._lock:
            connection = self._require_connection()
            now = datetime.now(UTC).isoformat()

            try:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO sessions
                    (session_id, created_at, updated_at, message_count)
                    VALUES (?, ?, ?, 0);
                    """,
                    (session_id, now, now),
                )
                connection.execute(
                    "INSERT INTO session_messages (session_id, role, content, created_at, token_count) "
                    "VALUES (?, ?, ?, ?, ?);",
                    (session_id, role, content, now, token_count),
                )
                connection.execute(
                    "UPDATE sessions SET message_count = message_count + 1, updated_at = ? "
                    "WHERE session_id = ?;",
                    (now, session_id),
                )
                connection.commit()

            except sqlite3.Error as ex:
                connection.rollback()
                raise SessionPersistenceError("Failed to append session message.") from ex

    def set_title(self, session_id: str, title: str) -> None:
        self._update_session_field(session_id, "title", title)

    def set_summary(self, session_id: str, summary: str) -> None:
        self._update_session_field(session_id, "summary", summary)

    def delete_session(self, session_id: str) -> bool:
        """
        Permanently delete a session and every one of its messages.

        Returns
        -------
        bool
            True if the session existed and was deleted; False if no
            such session existed.
        """

        with self._lock:
            connection = self._require_connection()

            try:
                connection.execute(
                    "DELETE FROM session_messages WHERE session_id = ?;", (session_id,)
                )
                cursor = connection.execute(
                    "DELETE FROM sessions WHERE session_id = ?;", (session_id,)
                )
                connection.commit()

                return cursor.rowcount > 0

            except sqlite3.Error as ex:
                connection.rollback()
                raise SessionPersistenceError("Failed to delete session.") from ex

    def export_session(self, session_id: str, *, path: Path) -> int:
        """
        Export one session's metadata and messages to `path` as JSON.

        Returns
        -------
        int
            The number of messages exported.

        Raises
        ------
        SessionNotFoundError
            If the session does not exist.
        """

        with self._lock:
            summary = self.get_session(session_id)

            if summary is None:
                raise SessionNotFoundError(f"Session '{session_id}' was not found.")

            messages = self.get_messages(session_id)

            payload = {
                "format_version": 1,
                "session_id": summary.session_id,
                "title": summary.title,
                "summary": summary.summary,
                "workspace_path": summary.workspace_path,
                "created_at": summary.created_at.isoformat(),
                "messages": [
                    {
                        "role": message.role,
                        "content": message.content,
                        "created_at": message.created_at.isoformat(),
                        "token_count": message.token_count,
                    }
                    for message in messages
                ],
            }

            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
            except OSError as ex:
                raise SessionPersistenceError(
                    f"Failed to export session to '{path}'."
                ) from ex

            return len(messages)

    def import_session(self, *, path: Path) -> str:
        """
        Import a session previously produced by `export_session()`.

        If the original `session_id` already exists, a fresh one is
        generated instead, so importing never overwrites an existing
        session.

        Returns
        -------
        str
            The id of the imported session (the original id, or a
            freshly generated one if it collided with an existing
            session).
        """

        with self._lock:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except OSError as ex:
                raise SessionPersistenceError(f"Failed to read import file '{path}'.") from ex
            except json.JSONDecodeError as ex:
                raise SessionPersistenceError(f"Import file '{path}' is not valid JSON.") from ex

            session_id = str(raw.get("session_id") or uuid4().hex)

            if self.get_session(session_id) is not None:
                session_id = uuid4().hex

            self.ensure_session(session_id, workspace_path=raw.get("workspace_path"))

            if raw.get("title"):
                self.set_title(session_id, str(raw["title"]))

            if raw.get("summary"):
                self.set_summary(session_id, str(raw["summary"]))

            for message in raw.get("messages", []):
                self.append_message(
                    session_id,
                    role=str(message["role"]),
                    content=str(message["content"]),
                    token_count=message.get("token_count"),
                )

            return session_id

    def _update_session_field(self, session_id: str, field_name: str, value: str) -> None:
        with self._lock:
            connection = self._require_connection()

            try:
                cursor = connection.execute(
                    f"UPDATE sessions SET {field_name} = ?, updated_at = ? WHERE session_id = ?;",
                    (value, datetime.now(UTC).isoformat(), session_id),
                )
                connection.commit()

                if cursor.rowcount == 0:
                    raise SessionNotFoundError(f"Session '{session_id}' was not found.")

            except sqlite3.Error as ex:
                connection.rollback()
                raise SessionPersistenceError("Failed to update session.") from ex

    def get_session(self, session_id: str) -> SessionSummary | None:
        with self._lock:
            connection = self._require_connection()

            try:
                row = connection.execute(
                    "SELECT * FROM sessions WHERE session_id = ?;", (session_id,)
                ).fetchone()

            except sqlite3.Error as ex:
                raise SessionPersistenceError("Failed to retrieve session.") from ex

            return _row_to_summary(row) if row is not None else None

    def list_sessions(self) -> tuple[SessionSummary, ...]:
        with self._lock:
            connection = self._require_connection()

            try:
                cursor = connection.execute("SELECT * FROM sessions ORDER BY updated_at DESC;")
                return tuple(_row_to_summary(row) for row in cursor.fetchall())

            except sqlite3.Error as ex:
                raise SessionPersistenceError("Failed to list sessions.") from ex

    def get_messages(self, session_id: str) -> tuple[SessionMessage, ...]:
        with self._lock:
            connection = self._require_connection()

            try:
                cursor = connection.execute(
                    "SELECT * FROM session_messages WHERE session_id = ? ORDER BY id;",
                    (session_id,),
                )
                return tuple(_row_to_message(row) for row in cursor.fetchall())

            except sqlite3.Error as ex:
                raise SessionPersistenceError("Failed to retrieve session messages.") from ex

    def search_messages(self, query_text: str, *, limit: int = 20) -> tuple[SessionMessage, ...]:
        """Lexical (FTS5 BM25) search across every session's messages."""

        with self._lock:
            connection = self._require_connection()

            try:
                cursor = connection.execute(
                    """
                    SELECT m.* FROM session_messages_fts
                    JOIN session_messages m ON m.id = session_messages_fts.rowid
                    WHERE session_messages_fts MATCH ?
                    ORDER BY bm25(session_messages_fts)
                    LIMIT ?;
                    """,
                    (_fts5_quote_query(query_text), limit),
                )
                return tuple(_row_to_message(row) for row in cursor.fetchall())

            except sqlite3.Error as ex:
                raise SessionPersistenceError("Failed to search session messages.") from ex

    def _require_connection(self) -> sqlite3.Connection:
        connection = self._connection

        if connection is None:
            raise SessionPersistenceError("Session store has not been initialized.")

        return connection


def _row_to_summary(row: sqlite3.Row) -> SessionSummary:
    return SessionSummary(
        session_id=row["session_id"],
        title=row["title"],
        summary=row["summary"],
        workspace_path=row["workspace_path"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        message_count=int(row["message_count"]),
    )


def _row_to_message(row: sqlite3.Row) -> SessionMessage:
    return SessionMessage(
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        created_at=datetime.fromisoformat(row["created_at"]),
        token_count=row["token_count"],
    )
