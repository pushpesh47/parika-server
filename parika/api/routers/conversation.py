"""
PARIKA API - Conversation Router

REST endpoints for conversation management:
- POST /api/v1/conversations - Create a new conversation
- GET /api/v1/conversations - List all conversations
- GET /api/v1/conversations/{conversation_id} - Get a conversation with its messages
- PATCH /api/v1/conversations/{conversation_id} - Update a conversation (rename)
- DELETE /api/v1/conversations/{conversation_id} - Delete a conversation
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Body, status

from ..auth.dependency import RequireAuth
from ..auth.backend import AuthContext
from ..dependencies import get_core_execution_owner
from ..handlers.conversation import (
    handle_list_conversations,
    handle_get_conversation,
    handle_delete_conversation,
    handle_update_conversation,
    handle_create_conversation,
)
from ..requests import ConversationListRequest, ConversationGetRequest, ConversationDeleteRequest, ConversationUpdateRequest, ConversationCreateRequest
from ..schemas.conversation import (
    ConversationListResponse,
    ConversationDetail,
    ConversationDeleteResponse,
    ConversationUpdateResponse,
    ConversationUpdateRequestBody,
    ConversationCreateRequestBody,
    ConversationCreateResponse,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreateRequestBody = Body(default=None),
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> ConversationCreateResponse:
    """
    Create a new conversation session.

    Creates a brand-new independent conversation with a unique ID.
    Optionally accepts an initial title.

    Returns the created conversation representation with its ID, title, and timestamps.

    Authentication:
        Requires valid authentication per [api.auth].mode configuration.

    Errors:
        401: Authentication required
        422: Validation error (empty/whitespace title or title too long)
        500: Session store unavailable
    """
    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: handle_create_conversation(
            core_execution_owner.runtime,
            core_execution_owner.session_store,
            ConversationCreateRequest(title=body.title if body else None),
        )
    )

    # Await the result without blocking the ASGI event loop
    result = await future

    return ConversationCreateResponse.model_validate(result)


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> ConversationListResponse:
    """
    List all stored conversation sessions.

    Returns a list of conversation summaries ordered by most recently updated first.

    Authentication:
        Requires valid authentication per [api.auth].mode configuration.

    Errors:
        401: Authentication required
        500: Session store unavailable
    """
    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: handle_list_conversations(
            core_execution_owner.runtime,
            core_execution_owner.session_store,
            ConversationListRequest(),
        )
    )

    # Await the result without blocking the ASGI event loop
    result = await future

    return ConversationListResponse.model_validate(result)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str = Path(..., description="Conversation session ID"),
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> ConversationDetail:
    """
    Get a specific conversation session by ID, including all its messages.

    Returns the full conversation details with all messages in chronological order.

    Authentication:
        Requires valid authentication per [api.auth].mode configuration.

    Errors:
        401: Authentication required
        404: Conversation not found
        500: Session store unavailable
    """
    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: handle_get_conversation(
            core_execution_owner.runtime,
            core_execution_owner.session_store,
            ConversationGetRequest(session_id=conversation_id),
        )
    )

    # Await the result without blocking the ASGI event loop
    result = await future

    return ConversationDetail.model_validate(result)


@router.patch("/{conversation_id}", response_model=ConversationUpdateResponse)
async def update_conversation(
    conversation_id: str = Path(..., description="Conversation session ID"),
    body: ConversationUpdateRequestBody = Body(...),
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> ConversationUpdateResponse:
    """
    Update a specific conversation session by ID (currently only title/rename).

    Returns the updated conversation representation with the new title.

    Authentication:
        Requires valid authentication per [api.auth].mode configuration.

    Errors:
        401: Authentication required
        404: Conversation not found
        422: Validation error (empty/whitespace title or title too long)
        500: Session store unavailable
    """
    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: handle_update_conversation(
            core_execution_owner.runtime,
            core_execution_owner.session_store,
            ConversationUpdateRequest(session_id=conversation_id, title=body.title),
        )
    )

    # Await the result without blocking the ASGI event loop
    result = await future

    return ConversationUpdateResponse.model_validate(result)


@router.delete("/{conversation_id}", response_model=ConversationDeleteResponse)
async def delete_conversation(
    conversation_id: str = Path(..., description="Conversation session ID"),
    auth: AuthContext = RequireAuth,
    core_execution_owner=Depends(get_core_execution_owner),
) -> ConversationDeleteResponse:
    """
    Delete a specific conversation session by ID.

    Permanently removes the session and all its messages from storage.
    The deleted conversation will no longer appear in subsequent listing requests.

    Authentication:
        Requires valid authentication per [api.auth].mode configuration.

    Errors:
        401: Authentication required
        500: Session store unavailable
    """
    # Submit the Core work to be executed on the Core worker thread
    future = core_execution_owner.submit(
        lambda: handle_delete_conversation(
            core_execution_owner.runtime,
            core_execution_owner.session_store,
            ConversationDeleteRequest(session_id=conversation_id),
        )
    )

    # Await the result without blocking the ASGI event loop
    result = await future

    return ConversationDeleteResponse.model_validate(result)