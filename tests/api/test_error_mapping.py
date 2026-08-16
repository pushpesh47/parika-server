"""
Tests for the centralized error-mapping table (section 14.2).
"""

from __future__ import annotations

import pytest

from parika.api.errors import _status_for_exception


class _FooNotFoundError(Exception):
    pass


class _FooAlreadyRegisteredError(Exception):
    pass


class _FooPermissionError(Exception):
    pass


@pytest.mark.parametrize(
    ("exception", "expected_status"),
    [
        (_FooNotFoundError("x"), 404),
        (_FooAlreadyRegisteredError("x"), 409),
        (_FooPermissionError("x"), 403),
        (NotImplementedError("x"), 501),
        (ValueError("x"), 500),
    ],
)
def test_status_for_exception(exception: Exception, expected_status: int) -> None:
    assert _status_for_exception(exception) == expected_status


def test_unknown_module_start_maps_to_404(client) -> None:
    response = client.post("/api/v1/modules/does-not-exist/start")
    assert response.status_code == 404

    body = response.json()
    assert body["error"]["type"] == "ModuleNotFoundError"
    assert "request_id" in body["error"]


def test_unknown_capability_maps_to_404(client) -> None:
    response = client.post(
        "/api/v1/capabilities/does.not.exist/execute", json={"arguments": {}}
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "CapabilityNotFoundError"


def test_invalid_request_body_maps_to_422(client) -> None:
    response = client.post("/api/v1/chat", json={"session_id": "s-1"})
    assert response.status_code == 422
