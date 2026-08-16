"""
Tests for `parika.server.app`'s lifespan wiring (section 5.1/5.4).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from parika.server.app import create_app


def test_health_answers_before_runtime_is_ready(runtime_factory) -> None:
    app = create_app(runtime_factory=runtime_factory)

    # /health never depends on ParikaRuntime existing.
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_ready_reports_ready_once_lifespan_has_started(runtime_factory) -> None:
    app = create_app(runtime_factory=runtime_factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


def test_live_answers_ok(runtime_factory) -> None:
    app = create_app(runtime_factory=runtime_factory)

    with TestClient(app) as client:
        response = client.get("/api/v1/live")
        assert response.status_code == 200


def test_lifespan_builds_exactly_one_runtime(runtime_factory) -> None:
    call_count = {"count": 0}

    def counting_factory():
        call_count["count"] += 1
        return runtime_factory()

    app = create_app(runtime_factory=counting_factory)

    with TestClient(app) as client:
        client.get("/api/v1/health")
        client.get("/api/v1/status")

    assert call_count["count"] == 1


def test_runtime_is_cleared_after_shutdown(runtime_factory) -> None:
    app = create_app(runtime_factory=runtime_factory)

    with TestClient(app):
        assert app.state.runtime is not None

    assert app.state.runtime is None


def test_web_client_is_served_as_a_static_bundle(runtime_factory) -> None:
    """
    The Expense Management Web Client (`web/`) is mounted as a plain
    static bundle at `/app` (see `_mount_web_client()`'s own
    docstring) - it never touches `/api/v1/...`, which remains the
    only JSON API surface.
    """

    app = create_app(runtime_factory=runtime_factory)

    with TestClient(app) as client:
        index_response = client.get("/app/")
        assert index_response.status_code == 200
        assert "text/html" in index_response.headers["content-type"]

        script_response = client.get("/app/app.js")
        assert script_response.status_code == 200
