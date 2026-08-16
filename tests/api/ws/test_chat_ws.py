"""
Tests for `WS /api/v1/ws/chat/{session_id}` (section 9.2).
"""

from __future__ import annotations


def test_websocket_chat_returns_done_message(client) -> None:
    with client.websocket_connect("/api/v1/ws/chat/s-ws-1") as websocket:
        websocket.send_json({"text": "Hello"})

        message = websocket.receive_json()

        # Without a real Provider, the turn fails gracefully; the very
        # last message received is always the terminal "done" message.
        while message.get("type") == "token":
            message = websocket.receive_json()

        assert message["type"] == "done"
        assert message["response"]["session_id"] == "s-ws-1"
