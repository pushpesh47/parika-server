"""
Tests for `GET /api/v1/providers`.
"""

from __future__ import annotations


def test_list_providers_returns_registered_providers(client) -> None:
    response = client.get("/api/v1/providers")

    assert response.status_code == 200

    body = response.json()
    provider_ids = {provider["id"] for provider in body["providers"]}

    assert "provider.ollama" in provider_ids
