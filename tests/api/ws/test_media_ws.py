"""
Tests for `WS /api/v1/ws/media/{client_id}` - the bidirectional Media
command/event transport.
"""

from __future__ import annotations

from parika.core.tool_manager.request import ToolRequest


def test_play_command_is_not_dispatched_before_media_ready(client) -> None:
    with client.websocket_connect("/api/v1/ws/media/test-client-5") as websocket:
        runtime = client.app.state.runtime

        # Connected, but this connection has not sent `media.ready`
        # yet - PARIKA must not claim the command was dispatched.
        response = runtime.tool_manager.execute(
            "tool.media_play",
            ToolRequest(arguments={"query": "https://youtu.be/dQw4w9WgXcQ"}),
        )

        assert response.result["status"] == "unavailable"


def test_websocket_receives_a_dispatched_play_command(client) -> None:
    with client.websocket_connect("/api/v1/ws/media/test-client-1") as websocket:
        websocket.send_json({"type": "media.ready"})

        runtime = client.app.state.runtime

        # `media.ready` is processed asynchronously on the connection's
        # own receive loop; poll (bounded, no fixed sleep) until the
        # connection is actually media-ready rather than racing a
        # fixed delay - mirroring this file's own polling convention
        # below for cross-thread eventual consistency.
        import time

        deadline = time.monotonic() + 2.0
        response = None

        while time.monotonic() < deadline:
            response = runtime.tool_manager.execute(
                "tool.media_play",
                ToolRequest(arguments={"query": "https://youtu.be/dQw4w9WgXcQ"}),
            )

            if response.result["status"] == "dispatched":
                break

        assert response is not None
        assert response.result["status"] == "dispatched"

        message = websocket.receive_json()
        assert message["type"] == "media.play"
        assert message["payload"]["source"]["type"] == "youtube"


def test_client_reported_state_change_reaches_get_state(client) -> None:
    with client.websocket_connect("/api/v1/ws/media/test-client-2") as websocket:
        websocket.send_json({"type": "media.play_started"})
        websocket.send_json({"type": "media.position_changed", "payload": {"position": 5.0}})

        # No reply is expected for recognized events; poll until the
        # REST snapshot reflects them (both are applied synchronously
        # inside the receive loop, but this avoids any race with the
        # TestClient's own message delivery timing).
        import time

        deadline = time.monotonic() + 2.0
        state = None

        while time.monotonic() < deadline:
            state = client.get("/api/v1/media/state").json()

            if state["status"] == "playing" and state["position"] == 5.0:
                break

        assert state is not None
        assert state["status"] == "playing"
        assert state["position"] == 5.0
        assert state["client_connected"] is True


def test_client_connected_becomes_false_after_disconnect(client) -> None:
    with client.websocket_connect("/api/v1/ws/media/test-client-3"):
        state = client.get("/api/v1/media/state").json()
        assert state["client_connected"] is True

    state = client.get("/api/v1/media/state").json()
    assert state["client_connected"] is False


def test_play_is_unavailable_while_no_client_is_connected(client) -> None:
    runtime = client.app.state.runtime

    response = runtime.tool_manager.execute(
        "tool.media_play",
        ToolRequest(arguments={"query": "https://youtu.be/dQw4w9WgXcQ"}),
    )

    assert response.result["status"] == "unavailable"


def test_unknown_event_type_reports_an_error_without_disconnecting(client) -> None:
    with client.websocket_connect("/api/v1/ws/media/test-client-4") as websocket:
        websocket.send_json({"type": "media.some_future_event"})

        message = websocket.receive_json()
        assert message["type"] == "error"

        # The connection itself remains open/usable afterward.
        websocket.send_json({"type": "media.ready"})
        websocket.send_json({"type": "media.play_started"})

        import time

        deadline = time.monotonic() + 2.0
        state = None

        while time.monotonic() < deadline:
            state = client.get("/api/v1/media/state").json()

            if state["status"] == "playing":
                break

        assert state is not None
        assert state["status"] == "playing"
