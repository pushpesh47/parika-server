"""
Tests for `GET /api/v1/config` and `POST /api/v1/reload`.
"""

from __future__ import annotations


def test_get_config_full_tree(client) -> None:
    response = client.get("/api/v1/config")

    assert response.status_code == 200
    body = response.json()
    assert body["key"] is None
    assert "application" in body["value"]


def test_get_config_single_key(client) -> None:
    response = client.get("/api/v1/config", params={"key": "application.name"})

    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "application.name"
    assert body["value"] == "PARIKA"


def test_reload_returns_expected_shape(client) -> None:
    response = client.post("/api/v1/reload")

    assert response.status_code == 200
    body = response.json()
    assert "reloaded_modules" in body
    assert "reconnected_providers" in body
    assert "failed_providers" in body
