"""
Tests for `GET /api/v1/capabilities` and the generic fallback
`POST /{capability_id}/execute` (section 8.3).
"""

from __future__ import annotations


def test_list_capabilities_returns_registered_capabilities(client) -> None:
    response = client.get("/api/v1/capabilities")

    assert response.status_code == 200

    body = response.json()
    capability_ids = {capability["id"] for capability in body["capabilities"]}

    assert "filesystem.read" in capability_ids
    assert "weather.current" in capability_ids or any(
        "weather" in cid for cid in capability_ids
    )


def test_execute_capability_via_generic_fallback(client, tmp_path) -> None:
    target_file = tmp_path / "hello.txt"
    target_file.write_text("hello from the generic capability endpoint")

    response = client.post(
        "/api/v1/capabilities/filesystem.read/execute",
        json={"arguments": {"path": str(target_file)}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["capability_id"] == "filesystem.read"
    assert body["result"]["content"] == "hello from the generic capability endpoint"


def test_execute_unknown_capability_returns_not_found(client) -> None:
    response = client.post(
        "/api/v1/capabilities/does.not.exist/execute",
        json={"arguments": {}},
    )

    assert response.status_code == 404


def test_execute_provider_backed_capability_returns_not_implemented(client) -> None:
    response = client.post(
        "/api/v1/capabilities/chat.respond/execute",
        json={"arguments": {}},
    )

    assert response.status_code == 501
