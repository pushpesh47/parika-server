"""
Tests for `GET /api/v1/media/state`.
"""

from __future__ import annotations


def test_get_state_returns_the_initial_idle_state(client) -> None:
    response = client.get("/api/v1/media/state")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "idle"
    assert body["client_connected"] is False
    assert body["source"] is None
