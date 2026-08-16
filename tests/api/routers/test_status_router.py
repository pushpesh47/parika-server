"""
Tests for `GET /api/v1/status`.
"""

from __future__ import annotations


def test_status_returns_expected_shape(client) -> None:
    response = client.get("/api/v1/status")

    assert response.status_code == 200

    body = response.json()

    assert "lifecycle_state" in body
    assert "overall_health" in body
    assert isinstance(body["registered_tools"], int)
    assert isinstance(body["providers"], list)


def test_status_includes_runtime_telemetry(client) -> None:
    """
    `GET /api/v1/status` must expose the same unified runtime/system
    telemetry the `/status` CLI command shows, sourced exclusively
    from `ResourceManager` - never fabricated when a metric is
    unavailable on the host running the test suite (e.g. no NVIDIA
    GPU, no readable temperature sensors).
    """

    response = client.get("/api/v1/status")

    assert response.status_code == 200

    body = response.json()

    # System
    assert body["system"]["platform"]
    assert body["system"]["architecture"]

    # CPU
    assert isinstance(body["cpu"]["usage_percent"], float)
    assert body["cpu"]["logical_core_count"] > 0

    # Memory (host RAM, distinct from `body["parika"]["memory_count"]`)
    assert body["memory"]["total_bytes"] > 0
    assert 0.0 <= body["memory"]["usage_percent"] <= 100.0

    # GPU: gracefully reported as not detected rather than failing the
    # request or crashing on a host with no NVML backend.
    assert body["gpu"]["detected"] in (True, False)
    assert isinstance(body["gpu"]["devices"], list)

    # Temperature: gracefully reported as unavailable rather than
    # fabricating a sensor reading.
    assert body["temperature"]["available"] in (True, False)
    assert isinstance(body["temperature"]["sensors"], list)

    # Storage: the PARIKA workspace filesystem, not every mount.
    assert body["storage"]["path"]
    assert body["storage"]["total_bytes"] > 0
    assert 0.0 <= body["storage"]["usage_percent"] <= 100.0

    # Network
    assert isinstance(body["network"]["available"], bool)

    # PARIKA-runtime counts
    assert body["parika"]["version"]
    assert isinstance(body["parika"]["available_providers"], int)
    assert isinstance(body["parika"]["memory_count"], int)
    assert isinstance(body["parika"]["knowledge_engines"], int)

    assert "timestamp" in body


def test_status_does_not_expose_secrets_or_env_vars(client) -> None:
    """
    Security/privacy regression: runtime telemetry must never leak
    provider API keys, credentials, or raw environment variables.
    """

    response = client.get("/api/v1/status")
    body = response.json()

    serialized = str(body).lower()

    for forbidden in ("api_key", "apikey", "secret", "password", "token"):
        assert forbidden not in serialized


def test_status_redacts_hostname_by_default(client) -> None:
    """
    `api.expose_hostname` defaults to `false`: the REST API must not
    leak the host machine's hostname to a network-reachable client
    unless an operator explicitly opts in.
    """

    response = client.get("/api/v1/status")
    body = response.json()

    assert body["system"]["hostname"] is None
    assert body["network"]["hostname"] is None
