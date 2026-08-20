"""
PARIKA Interfaces - Session Store - PostgreSQL Implementation

PostgreSQL-backed persistence for session-wise chat history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, UTC
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row


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


class PostgreSQLSessionStore:
    """PostgreSQL-backed persistence for sessions and their messages."""

    __slots__ = ("_pool", "_lock")

    def __init__(self, pool) -> None:
        self._pool = pool
        # PostgreSQL handles concurrency
        import threading
        self._lock = threading.Lock()

    def initialize(self) -> None:
        """No-op: schema is managed by Alembic migrations."""
        pass

    def shutdown(self) -> None:
        """No-op: pool is managed by PoolManager."""
        pass

    def ensure_session(
        self, session_id: str, *, workspace_path: str | None = None
    ) -> None:
        """Create a session row if it does not already exist. Idempotent."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    now = datetime.now(UTC).isoformat()
                    cur.execute(
                        """
                        INSERT INTO core.session
                        (session_id, workspace_path, created_at, updated_at, message_count)
                        VALUES (%s, %s, %s, %s, 0)
                        ON CONFLICT (session_id) DO NOTHING
                        """,
                        (session_id, workspace_path, now, now),
                    )
                    conn.commit()
                except psycopg.Error as ex:
                    conn.rollback()
                    raise SessionPersistenceError("Failed to create session.") from ex

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        token_count: int | None = None,
    ) -> None:
        """Persist one message and bump the owning session's message_count and updated_at."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    now = datetime.now(UTC).isoformat()
                    cur.execute(
                        """
                        INSERT INTO core.session
                        (session_id, created_at, updated_at, message_count)
                        VALUES (%s, %s, %s, 0)
                        ON CONFLICT (session_id) DO NOTHING
                        """,
                        (session_id, now, now),
                    )
                    cur.execute(
                        "INSERT INTO core.session_message (session_id, role, content, created_at, token_count) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (session_id, role, content, now, token_count),
                    )
                    cur.execute(
                        "UPDATE core.session SET message_count = message_count + 1, updated_at = %s "
                        "WHERE session_id = %s",
                        (now, session_id),
                    )
                    conn.commit()
                except psycopg.Error as ex:
                    conn.rollback()
                    raise SessionPersistenceError("Failed to append session message.") from ex

    def set_title(self, session_id: str, title: str) -> None:
        self._update_session_field(session_id, "title", title)

    def set_summary(self, session_id: str, summary: str) -> None:
        self._update_session_field(session_id, "summary", summary)

    def delete_session(self, session_id: str) -> bool:
        """Permanently delete a session and every one of its messages."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "DELETE FROM core.session_message WHERE session_id = %s",
                        (session_id,)
                    )
                    cur.execute(
                        "DELETE FROM core.session WHERE session_id = %s",
                        (session_id,)
                    )
                    conn.commit()
                    return cur.rowcount > 0
                except psycopg.Error as ex:
                    conn.rollback()
                    raise SessionPersistenceError("Failed to delete session.") from ex

    def export_session(self, session_id: str, *, path: Path) -> int:
        """Export one session's metadata and messages to `path` as JSON."""
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
            raise SessionPersistenceError(f"Failed to export session to '{path}'.") from ex

        return len(messages)

    def import_session(self, *, path: Path) -> str:
        """Import a session previously produced by `export_session()`."""
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
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        f"UPDATE core.session SET {field_name} = %s, updated_at = %s WHERE session_id = %s",
                        (value, datetime.now(UTC).isoformat(), session_id),
                    )
                    conn.commit()
                    if cur.rowcount == 0:
                        raise SessionNotFoundError(f"Session '{session_id}' was not found.")
                except psycopg.Error as ex:
                    conn.rollback()
                    raise SessionPersistenceError("Failed to update session.") from ex

    def get_session(self, session_id: str) -> SessionSummary | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        "SELECT * FROM core.session WHERE session_id = %s",
                        (session_id,)
                    )
                    row = cur.fetchone()
                    return self._row_to_summary(row) if row else None
                except psycopg.Error as ex:
                    raise SessionPersistenceError("Failed to retrieve session.") from ex

    def list_sessions(self) -> tuple[SessionSummary, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute("SELECT * FROM core.session ORDER BY updated_at DESC")
                    return tuple(self._row_to_summary(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise SessionPersistenceError("Failed to list sessions.") from ex

    def get_messages(self, session_id: str) -> tuple[SessionMessage, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        "SELECT * FROM core.session_message WHERE session_id = %s ORDER BY id",
                        (session_id,),
                    )
                    return tuple(self._row_to_message(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise SessionPersistenceError("Failed to retrieve session messages.") from ex

    def search_messages(self, query_text: str, *, limit: int = 20) -> tuple[SessionMessage, ...]:
        """Lexical (PostgreSQL full-text search) search across every session's messages."""
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                try:
                    cur.execute(
                        """
                        SELECT m.* FROM core.session_message m
                        WHERE m.search_vector @@ websearch_to_tsquery('simple', %s)
                        ORDER BY ts_rank_cd(m.search_vector, websearch_to_tsquery('simple', %s)) DESC
                        LIMIT %s
                        """,
                        (query_text, query_text, limit),
                    )
                    return tuple(self._row_to_message(row) for row in cur.fetchall())
                except psycopg.Error as ex:
                    raise SessionPersistenceError("Failed to search session messages.") from ex

    def _row_to_summary(self, row: dict) -> SessionSummary:
        return SessionSummary(
            session_id=row["session_id"],
            title=row["title"],
            summary=row["summary"],
            workspace_path=row["workspace_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            message_count=int(row["message_count"]),
        )

    def _row_to_message(self, row: dict) -> SessionMessage:
        return SessionMessage(
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
            token_count=row["token_count"],
        )