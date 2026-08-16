"""
Tests for `POST /api/v1/chat`.

No real Ollama server is required: without a reachable Provider, the
Goal still plans and executes through Brain/Planner/TaskManager
exactly as designed, but fails gracefully (reported through
`succeeded=False`, never a crash) -- matching README's own documented
behavior for this exact scenario.
"""

from __future__ import annotations


def test_chat_without_a_provider_fails_gracefully(client) -> None:
    response = client.post("/api/v1/chat", json={"text": "Hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["succeeded"] is False
    assert body["session_id"]


def test_chat_reuses_session_id_across_requests(client) -> None:
    first = client.post("/api/v1/chat", json={"text": "Hello", "session_id": "s-1"})
    second = client.post("/api/v1/chat", json={"text": "Again", "session_id": "s-1"})

    assert first.json()["session_id"] == "s-1"
    assert second.json()["session_id"] == "s-1"
