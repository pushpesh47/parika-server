"""
End-to-end tests that the configured `AuthenticationBackend` actually
gates `/api/v1/...` requests (section 10.5), using the real FastAPI
app and dependency wiring rather than a backend tested in isolation.

`[api.auth].mode` is read from `Configuration` (read-only, file-based
by design), so rather than writing a temporary config file, these
tests swap `app.state.auth_backend` after startup -- exercising
exactly the same `get_auth_context` dependency
(`parika/api/auth/dependency.py`) a real `api_key`/`jwt`-configured
deployment would use.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from parika.api.auth import ApiKeyBackend, configure_hashed_api_keys
from parika.server.app import create_app


def test_none_mode_allows_everything_without_credentials(runtime_factory) -> None:
    app = create_app(runtime_factory=runtime_factory)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/status")
        assert response.status_code == 200


def test_health_ready_live_never_require_auth(runtime_factory) -> None:
    app = create_app(runtime_factory=runtime_factory)

    with TestClient(app, raise_server_exceptions=False) as client:
        for path in ("/api/v1/health", "/api/v1/ready", "/api/v1/live"):
            response = client.get(path)
            assert response.status_code in (200, 503)


def test_api_key_mode_rejects_missing_credential(runtime_factory) -> None:
    app = create_app(runtime_factory=runtime_factory)

    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.auth_backend = ApiKeyBackend(
            hashed_keys=configure_hashed_api_keys(["real-key"])
        )

        response = client.get("/api/v1/status")
        assert response.status_code == 401


def test_api_key_mode_accepts_valid_bearer_token(runtime_factory) -> None:
    app = create_app(runtime_factory=runtime_factory)

    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.auth_backend = ApiKeyBackend(
            hashed_keys=configure_hashed_api_keys(["real-key"])
        )

        response = client.get(
            "/api/v1/status", headers={"Authorization": "Bearer real-key"}
        )
        assert response.status_code == 200


def test_api_key_mode_accepts_x_api_key_header(runtime_factory) -> None:
    app = create_app(runtime_factory=runtime_factory)

    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.auth_backend = ApiKeyBackend(
            hashed_keys=configure_hashed_api_keys(["real-key"])
        )

        response = client.get("/api/v1/status", headers={"X-API-Key": "real-key"})
        assert response.status_code == 200


def test_api_key_mode_rejects_wrong_key(runtime_factory) -> None:
    app = create_app(runtime_factory=runtime_factory)

    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.auth_backend = ApiKeyBackend(
            hashed_keys=configure_hashed_api_keys(["real-key"])
        )

        response = client.get(
            "/api/v1/status", headers={"Authorization": "Bearer wrong-key"}
        )
        assert response.status_code == 401
