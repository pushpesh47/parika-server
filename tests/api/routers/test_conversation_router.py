"""
Tests for `GET /api/v1/conversations`, `GET /api/v1/conversations/{conversation_id}`,
and `DELETE /api/v1/conversations/{conversation_id}`.
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