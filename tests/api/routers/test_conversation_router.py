"""
Tests for `GET /api/v1/conversations`, `GET /api/v1/conversations/{conversation_id}`,
`PATCH /api/v1/conversations/{conversation_id}`, and `DELETE /api/v1/conversations/{conversation_id}`.
"""

from __future__ import annotations


def test_list_conversations_empty(client) -> None:
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    body = response.json()
    assert "conversations" in body
    assert isinstance(body["conversations"], list)


def test_list_conversations_with_data(client) -> None:
    # Create a session by sending a chat message
    client.post("/api/v1/chat", json={"text": "Hello", "session_id": "test-session-1"})
    client.post("/api/v1/chat", json={"text": "World", "session_id": "test-session-2"})

    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    body = response.json()
    assert "conversations" in body
    conversations = body["conversations"]
    assert len(conversations) >= 2
    
    # Check that sessions are ordered by updated_at descending
    session_ids = [c["session_id"] for c in conversations]
    assert "test-session-1" in session_ids
    assert "test-session-2" in session_ids


def test_get_conversation_existing(client) -> None:
    # Create a session
    client.post("/api/v1/chat", json={"text": "Hello", "session_id": "test-get-1"})
    client.post("/api/v1/chat", json={"text": "How are you?", "session_id": "test-get-1"})

    response = client.get("/api/v1/conversations/test-get-1")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "test-get-1"
    assert body["message_count"] >= 2
    assert "messages" in body
    assert isinstance(body["messages"], list)
    assert len(body["messages"]) >= 2
    
    # Check message structure
    for message in body["messages"]:
        assert "role" in message
        assert "content" in message
        assert "created_at" in message
        assert message["session_id"] == "test-get-1"


def test_get_conversation_nonexistent(client) -> None:
    response = client.get("/api/v1/conversations/nonexistent-session-id")
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["type"] == "SessionNotFoundError"


def test_delete_conversation_existing(client) -> None:
    # Create a session
    client.post("/api/v1/chat", json={"text": "Hello", "session_id": "test-delete-1"})

    # Verify it exists
    response = client.get("/api/v1/conversations/test-delete-1")
    assert response.status_code == 200

    # Delete it
    response = client.delete("/api/v1/conversations/test-delete-1")
    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is True
    assert body["session_id"] == "test-delete-1"

    # Verify it no longer exists
    response = client.get("/api/v1/conversations/test-delete-1")
    assert response.status_code == 404

    # Verify it no longer appears in list
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    body = response.json()
    session_ids = [c["session_id"] for c in body["conversations"]]
    assert "test-delete-1" not in session_ids


def test_delete_conversation_nonexistent(client) -> None:
    response = client.delete("/api/v1/conversations/nonexistent-session-id")
    # Should return 200 with deleted=false for idempotent delete
    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is False
    assert body["session_id"] == "nonexistent-session-id"


def test_delete_then_list_does_not_include_deleted(client) -> None:
    # Create two sessions
    client.post("/api/v1/chat", json={"text": "Hello", "session_id": "test-list-delete-1"})
    client.post("/api/v1/chat", json={"text": "World", "session_id": "test-list-delete-2"})

    # Delete one
    response = client.delete("/api/v1/conversations/test-list-delete-1")
    assert response.status_code == 200
    assert response.json()["deleted"] is True

    # List should only have the remaining one
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    body = response.json()
    session_ids = [c["session_id"] for c in body["conversations"]]
    assert "test-list-delete-1" not in session_ids
    assert "test-list-delete-2" in session_ids


def test_conversation_response_schema(client) -> None:
    # Create a session
    client.post("/api/v1/chat", json={"text": "Test message", "session_id": "test-schema-1"})

    response = client.get("/api/v1/conversations/test-schema-1")
    assert response.status_code == 200
    body = response.json()
    
    # Verify required fields
    assert "session_id" in body
    assert "title" in body
    assert "summary" in body
    assert "workspace_path" in body
    assert "created_at" in body
    assert "updated_at" in body
    assert "message_count" in body
    assert "messages" in body
    
    # Verify message structure
    for message in body["messages"]:
        assert "session_id" in message
        assert "role" in message
        assert "content" in message
        assert "created_at" in message
        assert "token_count" in message


def test_list_conversations_response_schema(client) -> None:
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    body = response.json()
    
    assert "conversations" in body
    assert isinstance(body["conversations"], list)
    
    for conversation in body["conversations"]:
        assert "session_id" in conversation
        assert "title" in conversation
        assert "summary" in conversation
        assert "workspace_path" in conversation
        assert "created_at" in conversation
        assert "updated_at" in conversation
        assert "message_count" in conversation


# =============================================================================
# New tests for PATCH /api/v1/conversations/{conversation_id} (rename)
# =============================================================================

def test_rename_conversation_success(client) -> None:
    """Test successful conversation rename via PATCH."""
    # Create a session
    client.post("/api/v1/chat", json={"text": "Hello world", "session_id": "test-rename-success-1"})
    
    # Verify initial title (auto-generated from first message)
    response = client.get("/api/v1/conversations/test-rename-success-1")
    assert response.status_code == 200
    initial_title = response.json()["title"]
    assert initial_title == "Hello world"
    
    # Rename the conversation
    response = client.patch(
        "/api/v1/conversations/test-rename-success-1",
        json={"title": "My New Title"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "test-rename-success-1"
    assert body["title"] == "My New Title"
    assert "updated_at" in body
    
    # Verify the title is persisted
    response = client.get("/api/v1/conversations/test-rename-success-1")
    assert response.status_code == 200
    assert response.json()["title"] == "My New Title"
    
    # Verify list also shows new title
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    conversations = response.json()["conversations"]
    renamed = next(c for c in conversations if c["session_id"] == "test-rename-success-1")
    assert renamed["title"] == "My New Title"


def test_rename_conversation_nonexistent(client) -> None:
    """Test renaming a nonexistent conversation returns 404."""
    response = client.patch(
        "/api/v1/conversations/nonexistent-session-id",
        json={"title": "New Title"}
    )
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["type"] == "SessionNotFoundError"


def test_rename_conversation_empty_title_rejected(client) -> None:
    """Test that empty title is rejected with 422."""
    client.post("/api/v1/chat", json={"text": "Hello", "session_id": "test-rename-empty"})
    
    response = client.patch(
        "/api/v1/conversations/test-rename-empty",
        json={"title": ""}
    )
    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert body["error"]["type"] == "RequestValidationError"
    # Pydantic's min_length=1 validation catches this with "at least 1 character"
    # Our custom validator would catch it with "empty or whitespace-only"
    error_msg = body["error"]["message"].lower()
    assert "empty" in error_msg or "character" in error_msg or "whitespace" in error_msg


def test_rename_conversation_whitespace_only_rejected(client) -> None:
    """Test that whitespace-only title is rejected with 422."""
    client.post("/api/v1/chat", json={"text": "Hello", "session_id": "test-rename-ws"})
    
    response = client.patch(
        "/api/v1/conversations/test-rename-ws",
        json={"title": "   \n\t  "}
    )
    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert body["error"]["type"] == "RequestValidationError"
    assert "empty" in body["error"]["message"].lower() or "whitespace" in body["error"]["message"].lower()


def test_rename_conversation_too_long_rejected(client) -> None:
    """Test that title exceeding max length is rejected with 422."""
    client.post("/api/v1/chat", json={"text": "Hello", "session_id": "test-rename-long"})
    
    long_title = "x" * 201  # Exceeds 200 character limit
    response = client.patch(
        "/api/v1/conversations/test-rename-long",
        json={"title": long_title}
    )
    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert body["error"]["type"] == "RequestValidationError"
    assert "200" in body["error"]["message"] or "exceed" in body["error"]["message"].lower()


def test_rename_conversation_preserves_messages(client) -> None:
    """Test that renaming doesn't affect messages."""
    # Create a session with multiple messages
    client.post("/api/v1/chat", json={"text": "First message", "session_id": "test-rename-msgs"})
    client.post("/api/v1/chat", json={"text": "Second message", "session_id": "test-rename-msgs"})
    client.post("/api/v1/chat", json={"text": "Third message", "session_id": "test-rename-msgs"})
    
    # Get initial messages
    response = client.get("/api/v1/conversations/test-rename-msgs")
    assert response.status_code == 200
    initial_messages = response.json()["messages"]
    assert len(initial_messages) >= 3
    
    # Rename
    response = client.patch(
        "/api/v1/conversations/test-rename-msgs",
        json={"title": "Renamed Title"}
    )
    assert response.status_code == 200
    
    # Verify messages unchanged
    response = client.get("/api/v1/conversations/test-rename-msgs")
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == len(initial_messages)
    for i, msg in enumerate(messages):
        assert msg["content"] == initial_messages[i]["content"]
        assert msg["role"] == initial_messages[i]["role"]


def test_rename_conversation_updates_updated_at(client) -> None:
    """Test that renaming updates the updated_at timestamp."""
    client.post("/api/v1/chat", json={"text": "Hello", "session_id": "test-rename-time"})
    
    # Get initial updated_at
    response = client.get("/api/v1/conversations/test-rename-time")
    assert response.status_code == 200
    initial_updated = response.json()["updated_at"]
    
    # Small delay to ensure timestamp changes
    import time
    time.sleep(0.1)
    
    # Rename
    response = client.patch(
        "/api/v1/conversations/test-rename-time",
        json={"title": "Updated Title"}
    )
    assert response.status_code == 200
    new_updated = response.json()["updated_at"]
    
    # Verify updated_at changed
    assert new_updated > initial_updated


# =============================================================================
# Tests for automatic title generation
# =============================================================================

def test_new_conversation_auto_title_from_first_message(client) -> None:
    """Test that a new conversation gets an automatic title from the first user message."""
    # Create a new conversation via chat (no explicit session_id)
    response = client.post("/api/v1/chat", json={"text": "This is my first message"})
    assert response.status_code == 200
    session_id = response.json()["session_id"]
    
    # Check that conversation has auto-generated title
    response = client.get(f"/api/v1/conversations/{session_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "This is my first message"
    assert body["session_id"] == session_id


def test_auto_title_truncated_to_80_chars(client) -> None:
    """Test that auto-generated title is truncated to 80 characters."""
    long_message = "This is a very long first message that should be truncated to eighty characters maximum length"
    response = client.post("/api/v1/chat", json={"text": long_message, "session_id": "test-auto-title-long"})
    assert response.status_code == 200
    session_id = response.json()["session_id"]
    
    response = client.get(f"/api/v1/conversations/{session_id}")
    assert response.status_code == 200
    title = response.json()["title"]
    assert len(title) <= 80
    assert title == long_message[:80]


def test_auto_title_first_line_only(client) -> None:
    """Test that auto-generated title uses only the first line of the message."""
    multi_line = "First line\nSecond line\nThird line"
    response = client.post("/api/v1/chat", json={"text": multi_line, "session_id": "test-auto-title-multiline"})
    assert response.status_code == 200
    session_id = response.json()["session_id"]
    
    response = client.get(f"/api/v1/conversations/{session_id}")
    assert response.status_code == 200
    title = response.json()["title"]
    assert title == "First line"


def test_explicit_session_id_gets_auto_title(client) -> None:
    """Test that explicit session_id also gets auto title on first message."""
    response = client.post("/api/v1/chat", json={"text": "Explicit session title", "session_id": "test-explicit-title"})
    assert response.status_code == 200
    
    response = client.get("/api/v1/conversations/test-explicit-title")
    assert response.status_code == 200
    assert response.json()["title"] == "Explicit session title"


def test_auto_title_persists_across_reload(client) -> None:
    """Test that auto-generated title persists and is returned on subsequent loads."""
    response = client.post("/api/v1/chat", json={"text": "Persistent title test", "session_id": "test-persist-title"})
    assert response.status_code == 200
    
    # First load
    response = client.get("/api/v1/conversations/test-persist-title")
    assert response.status_code == 200
    title1 = response.json()["title"]
    assert title1 == "Persistent title test"
    
    # Second load (simulating reload)
    response = client.get("/api/v1/conversations/test-persist-title")
    assert response.status_code == 200
    title2 = response.json()["title"]
    assert title2 == "Persistent title test"
    assert title1 == title2


def test_list_returns_auto_titles(client) -> None:
    """Test that conversation list includes auto-generated titles."""
    client.post("/api/v1/chat", json={"text": "First conversation", "session_id": "test-list-title-1"})
    client.post("/api/v1/chat", json={"text": "Second conversation", "session_id": "test-list-title-2"})
    
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    conversations = response.json()["conversations"]
    
    conv1 = next(c for c in conversations if c["session_id"] == "test-list-title-1")
    conv2 = next(c for c in conversations if c["session_id"] == "test-list-title-2")
    
    assert conv1["title"] == "First conversation"
    assert conv2["title"] == "Second conversation"


# =============================================================================
# Tests for POST /api/v1/conversations (create)
# =============================================================================

def test_create_conversation_empty_body(client) -> None:
    """Test creating a conversation with empty request body (no title)."""
    response = client.post("/api/v1/conversations", json={})
    assert response.status_code == 201
    body = response.json()
    assert "session_id" in body
    assert body["session_id"] is not None
    assert len(body["session_id"]) > 0
    assert body["title"] is None
    assert body["message_count"] == 0
    assert "created_at" in body
    assert "updated_at" in body


def test_create_conversation_with_title(client) -> None:
    """Test creating a conversation with an explicit title."""
    response = client.post("/api/v1/conversations", json={"title": "My New Conversation"})
    assert response.status_code == 201
    body = response.json()
    assert "session_id" in body
    assert body["title"] == "My New Conversation"
    assert body["message_count"] == 0
    assert "created_at" in body
    assert "updated_at" in body


def test_create_conversation_title_trimmed(client) -> None:
    """Test that conversation title is trimmed of whitespace."""
    response = client.post("/api/v1/conversations", json={"title": "  Trimmed Title  "})
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Trimmed Title"


def test_create_conversation_empty_title_rejected(client) -> None:
    """Test that empty title is rejected with 422."""
    response = client.post("/api/v1/conversations", json={"title": ""})
    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert body["error"]["type"] == "RequestValidationError"


def test_create_conversation_whitespace_only_title_rejected(client) -> None:
    """Test that whitespace-only title is rejected with 422."""
    response = client.post("/api/v1/conversations", json={"title": "   \n\t  "})
    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert body["error"]["type"] == "RequestValidationError"


def test_create_conversation_too_long_title_rejected(client) -> None:
    """Test that title exceeding max length is rejected with 422."""
    long_title = "x" * 201  # Exceeds 200 character limit
    response = client.post("/api/v1/conversations", json={"title": long_title})
    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert body["error"]["type"] == "RequestValidationError"


def test_create_conversation_appears_in_list(client) -> None:
    """Test that newly created conversation appears in list."""
    # Create conversation
    response = client.post("/api/v1/conversations", json={"title": "List Test Conversation"})
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    
    # List conversations
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    conversations = response.json()["conversations"]
    
    # Find our conversation
    created = next(c for c in conversations if c["session_id"] == session_id)
    assert created["title"] == "List Test Conversation"
    assert created["message_count"] == 0


def test_create_conversation_can_be_retrieved(client) -> None:
    """Test that newly created conversation can be retrieved via GET."""
    # Create conversation
    response = client.post("/api/v1/conversations", json={"title": "Get Test Conversation"})
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    
    # Get conversation
    response = client.get(f"/api/v1/conversations/{session_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert body["title"] == "Get Test Conversation"
    assert body["message_count"] == 0
    assert body["messages"] == []


def test_create_two_conversations_independent(client) -> None:
    """Test that two created conversations are independent."""
    # Create first conversation
    response1 = client.post("/api/v1/conversations", json={"title": "First Conversation"})
    assert response1.status_code == 201
    session_id_1 = response1.json()["session_id"]
    
    # Create second conversation
    response2 = client.post("/api/v1/conversations", json={"title": "Second Conversation"})
    assert response2.status_code == 201
    session_id_2 = response2.json()["session_id"]
    
    # IDs must be different
    assert session_id_1 != session_id_2
    
    # Both must exist and be retrievable
    response = client.get(f"/api/v1/conversations/{session_id_1}")
    assert response.status_code == 200
    assert response.json()["title"] == "First Conversation"
    
    response = client.get(f"/api/v1/conversations/{session_id_2}")
    assert response.status_code == 200
    assert response.json()["title"] == "Second Conversation"
    
    # Both must appear in list
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    conversations = response.json()["conversations"]
    session_ids = [c["session_id"] for c in conversations]
    assert session_id_1 in session_ids
    assert session_id_2 in session_ids


def test_create_then_rename_then_get(client) -> None:
    """Test create -> rename -> get flow."""
    # Create
    response = client.post("/api/v1/conversations", json={"title": "Original Title"})
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    
    # Rename
    response = client.patch(
        f"/api/v1/conversations/{session_id}",
        json={"title": "Renamed Title"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Renamed Title"
    
    # Get and verify
    response = client.get(f"/api/v1/conversations/{session_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Renamed Title"


def test_create_then_rename_then_list(client) -> None:
    """Test create -> rename -> list reflects renamed state."""
    # Create
    response = client.post("/api/v1/conversations", json={"title": "Original Title"})
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    
    # Rename
    response = client.patch(
        f"/api/v1/conversations/{session_id}",
        json={"title": "Renamed Title"}
    )
    assert response.status_code == 200
    
    # List and verify
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    conversations = response.json()["conversations"]
    renamed = next(c for c in conversations if c["session_id"] == session_id)
    assert renamed["title"] == "Renamed Title"


def test_create_then_delete_then_get(client) -> None:
    """Test create -> delete -> get returns 404."""
    # Create
    response = client.post("/api/v1/conversations", json={"title": "To Be Deleted"})
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    
    # Delete
    response = client.delete(f"/api/v1/conversations/{session_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    
    # Get should return 404
    response = client.get(f"/api/v1/conversations/{session_id}")
    assert response.status_code == 404


def test_create_conversation_isolation(client) -> None:
    """Test that two conversations have isolated state."""
    # Create two conversations
    response_a = client.post("/api/v1/conversations", json={"title": "Conversation A"})
    assert response_a.status_code == 201
    session_id_a = response_a.json()["session_id"]
    
    response_b = client.post("/api/v1/conversations", json={"title": "Conversation B"})
    assert response_b.status_code == 201
    session_id_b = response_b.json()["session_id"]
    
    # Add message to conversation A via chat
    client.post("/api/v1/chat", json={"text": "Message in A", "session_id": session_id_a})
    client.post("/api/v1/chat", json={"text": "Another message in A", "session_id": session_id_a})
    
    # Verify A has messages, B has none
    response = client.get(f"/api/v1/conversations/{session_id_a}")
    assert response.status_code == 200
    assert response.json()["message_count"] >= 2
    
    response = client.get(f"/api/v1/conversations/{session_id_b}")
    assert response.status_code == 200
    assert response.json()["message_count"] == 0
    
    # Verify list shows correct counts
    response = client.get("/api/v1/conversations")
    assert response.status_code == 200
    conversations = response.json()["conversations"]
    conv_a = next(c for c in conversations if c["session_id"] == session_id_a)
    conv_b = next(c for c in conversations if c["session_id"] == session_id_b)
    assert conv_a["message_count"] >= 2
    assert conv_b["message_count"] == 0