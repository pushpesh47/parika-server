"""
PARIKA API - Conversation Handlers

Translates conversation management requests into calls against the existing
InterfaceSession and PostgreSQLSessionStore, and translates the results
back into plain, JSON-serializable values.

These handlers never implement new decision logic -- they only orchestrate
existing Core/Interface layer methods.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from parika.interfaces.runtime import ParikaRuntime
from parika.interfaces.postgresql_session_store import PostgreSQLSessionStore, SessionNotFoundError

from ..requests import ConversationListRequest, ConversationGetRequest, ConversationDeleteRequest, ConversationUpdateRequest


def handle_list_conversations(
    runtime: ParikaRuntime,
    session_store: PostgreSQLSessionStore,
    request: ConversationListRequest,
) -> dict[str, Any]:
    """
    List all stored conversation sessions.

    Returns a list of conversation summaries ordered by most recently updated first.
    """
    summaries = session_store.list_sessions()

    return {
        "conversations": [
            {
                "session_id": summary.session_id,
                "title": summary.title,
                "summary": summary.summary,
                "workspace_path": summary.workspace_path,
                "created_at": summary.created_at.isoformat(),
                "updated_at": summary.updated_at.isoformat(),
                "message_count": summary.message_count,
            }
            for summary in summaries
        ]
    }


def handle_get_conversation(
    runtime: ParikaRuntime,
    session_store: PostgreSQLSessionStore,
    request: ConversationGetRequest,
) -> dict[str, Any]:
    """
    Get a specific conversation session by ID, including all its messages.

    Raises SessionNotFoundError if the session doesn't exist.
    """
    summary = session_store.get_session(request.session_id)

    if summary is None:
        raise SessionNotFoundError(f"Session '{request.session_id}' was not found.")

    messages = session_store.get_messages(request.session_id)

    return {
        "session_id": summary.session_id,
        "title": summary.title,
        "summary": summary.summary,
        "workspace_path": summary.workspace_path,
        "created_at": summary.created_at.isoformat(),
        "updated_at": summary.updated_at.isoformat(),
        "message_count": summary.message_count,
        "messages": [
            {
                "session_id": message.session_id,
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
                "token_count": message.token_count,
            }
            for message in messages
        ],
    }


def handle_delete_conversation(
    runtime: ParikaRuntime,
    session_store: PostgreSQLSessionStore,
    request: ConversationDeleteRequest,
) -> dict[str, Any]:
    """
    Delete a specific conversation session by ID.

    Returns whether the deletion succeeded and the session ID.
    """
    deleted = session_store.delete_session(request.session_id)

    return {
        "deleted": deleted,
        "session_id": request.session_id,
    }


def handle_update_conversation(
    runtime: ParikaRuntime,
    session_store: PostgreSQLSessionStore,
    request: ConversationUpdateRequest,
) -> dict[str, Any]:
    """
    Update a specific conversation session by ID (currently only title).

    Raises SessionNotFoundError if the session doesn't exist.
    """
    summary = session_store.get_session(request.session_id)

    if summary is None:
        raise SessionNotFoundError(f"Session '{request.session_id}' was not found.")

    session_store.set_title(request.session_id, request.title)

    # Return updated session info
    updated_summary = session_store.get_session(request.session_id)
    return {
        "session_id": updated_summary.session_id,
        "title": updated_summary.title,
        "updated_at": updated_summary.updated_at.isoformat(),
    }