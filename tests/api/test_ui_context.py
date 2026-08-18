"""
Tests for UI Context REST API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from parika.api.routers import build_v1_router
from parika.core.ui_context.state import (
    UIContextState,
    SurfaceItem,
    ContextSource,
    AttentionLevel,
    UrgencyLevel,
    FocusArea,
    SurfaceTier,
)


@pytest.fixture
def mock_runtime():
    """Create a mock runtime with UI context projector."""
    runtime = MagicMock()
    projector = MagicMock()
    projector.is_ready.return_value = True
    
    # Create a sample state
    surfaces = (
        SurfaceItem(
            capability_id="weather.current",
            label="Current Conditions",
            tier=SurfaceTier.PRIMARY,
        ),
    )
    
    state = UIContextState(
        version=1,
        context="weather",
        confidence=0.95,
        source=ContextSource.TASK,
        attention=AttentionLevel.PRIMARY,
        urgency=UrgencyLevel.NORMAL,
        focus=FocusArea.CURRENT_CONDITIONS,
        surfaces=surfaces,
        timestamp=datetime.now(UTC),
        metadata=MappingProxyType({"task_id": "abc123"}),
    )
    
    projector.get_current_state.return_value = state
    runtime.ui_context_projector = projector
    
    return runtime


@pytest.fixture
def client(mock_runtime):
    """Create a test client with mocked runtime."""
    from fastapi import FastAPI
    from parika.api.auth.backend import AuthenticationBackend, AuthContext
    
    app = FastAPI()
    app.include_router(build_v1_router())
    
    # Mock auth backend
    auth_backend = MagicMock(spec=AuthenticationBackend)
    auth_backend.authenticate.return_value = AuthContext(
        subject="test_user",
        mode="api_key",
    )
    app.state.auth_backend = auth_backend
    app.state.runtime = mock_runtime
    
    return TestClient(app)


class TestUIContextREST:
    """Tests for UI Context REST endpoint."""
    
    def test_get_ui_context_success(self, client, mock_runtime):
        """Test successful UI context retrieval."""
        response = client.get("/api/v1/ui/context", headers={"Authorization": "Bearer test_token"})
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["version"] == 1
        assert data["context"] == "weather"
        assert data["confidence"] == 0.95
        assert data["source"] == "task"
        assert data["attention"] == "primary"
        assert data["urgency"] == "normal"
        assert data["focus"] == "current_conditions"
        assert len(data["surfaces"]) == 1
        assert data["surfaces"][0]["capability_id"] == "weather.current"
        assert data["surfaces"][0]["tier"] == "primary"
    
    def test_get_ui_context_with_auth(self, client):
        """Test UI context with valid authentication."""
        response = client.get("/api/v1/ui/context", headers={"Authorization": "Bearer test_token"})
        
        # Should succeed with our mock auth
        assert response.status_code == 200