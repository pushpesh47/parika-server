"""
Tests for `GET /api/v1/modules` and `POST /{module_id}/start`/`/stop`.
"""

from __future__ import annotations


def test_list_modules_returns_registered_modules(client) -> None:
    response = client.get("/api/v1/modules")

    assert response.status_code == 200

    body = response.json()
    module_ids = {module["id"] for module in body["modules"]}

    assert "filesystem" in module_ids


def test_stop_then_start_module(client) -> None:
    stop_response = client.post("/api/v1/modules/weather/stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["state"] == "inactive"

    start_response = client.post("/api/v1/modules/weather/start")
    assert start_response.status_code == 200
    assert start_response.json()["state"] == "active"


def test_start_already_active_module_returns_conflict(client) -> None:
    response = client.post("/api/v1/modules/weather/start")

    assert response.status_code == 409


def test_unknown_module_returns_not_found(client) -> None:
    response = client.post("/api/v1/modules/does-not-exist/start")

    assert response.status_code == 404
