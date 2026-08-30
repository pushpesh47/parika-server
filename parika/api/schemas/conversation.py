"""
PARIKA API - Conversation Schemas

Wire-format request/response for conversation management endpoints:
- POST /api/v1/conversations - Create a new conversation
- GET /api/v1/conversations - List all conversations
- GET /api/v1/conversations/{conversation_id} - Get a conversation with its messages
- PATCH /api/v1/conversations/{conversation_id} - Update a conversation (rename)
- DELETE /api/v1/conversations/{conversation_id} - Delete a conversation
"""

from __future__ import annotations

from .common import ApiModel
from datetime import datetime
from pydantic import Field, field_validator
from typing import Annotated, Optional


class ConversationSummary(ApiModel):
    """Summary of a conversation session for listing."""

    session_id: str
    title: str | None = None
    summary: str | None = None
    workspace_path: str | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationMessage(ApiModel):
    """A single message within a conversation."""

    session_id: str
    role: str
    content: str
    created_at: datetime
    token_count: int | None = None


class ConversationDetail(ApiModel):
    """Full conversation details including messages."""

    session_id: str
    title: str | None = None
    summary: str | None = None
    workspace_path: str | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int
    messages: list[ConversationMessage]


class ConversationListResponse(ApiModel):
    """Response for listing conversations."""

    conversations: list[ConversationSummary]


class ConversationCreateRequestBody(ApiModel):
    """Request body for creating a new conversation."""

    title: Optional[Annotated[str, Field(min_length=1, max_length=200, description="Optional initial conversation title (1-200 characters, no whitespace-only)")]] = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str | None) -> str | None:
        """Validate conversation title: not empty, not whitespace-only, reasonable length."""
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Title cannot be empty or whitespace-only")
        if len(stripped) > 200:
            raise ValueError("Title cannot exceed 200 characters")
        return stripped


class ConversationCreateResponse(ApiModel):
    """Response for creating a new conversation."""

    session_id: str
    title: str | None = None
    summary: str | None = None
    workspace_path: str | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationDeleteResponse(ApiModel):
    """Response for deleting a conversation."""

    deleted: bool
    session_id: str


class ConversationUpdateRequestBody(ApiModel):
    """Request body for updating a conversation (currently only title)."""

    title: Annotated[str, Field(min_length=1, max_length=200, description="Conversation display name (1-200 characters, no whitespace-only)")]

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        """Validate conversation title: not empty, not whitespace-only, reasonable length."""
        if value is None:
            raise ValueError("Title is required")
        stripped = value.strip()
        if not stripped:
            raise ValueError("Title cannot be empty or whitespace-only")
        if len(stripped) > 200:
            raise ValueError("Title cannot exceed 200 characters")
        return stripped


class ConversationUpdateResponse(ApiModel):
    """Response for updating a conversation."""

    session_id: str
    title: str
    updated_at: datetime