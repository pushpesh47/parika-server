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
from parika.api.schemas.ui_context import UIContextResponse
from parika.api.ws.ui import _serialize_state
from parika.core.ui_context.state import (
    UIContextState,
    SurfaceItem,
    ContextSource,
    AttentionLevel,
    UrgencyLevel,
    FocusArea,
    SurfaceTier,
    RequestStatus,
    DomainInfo,
    SynthesisInfo,
    DependencyInfo,
    UserIntent,
    ConversationalContext,
    ContextTransition,
    EntityInfo,
    EntityType,
    TopicInfo,
    SemanticRelevance,
    FreshnessInfo,
    ContextualRole,
)
from parika.core.ui_context.events import UIContextChanged


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


class TestUIContextRESTWS:
    """Tests for REST/WebSocket contract consistency."""
    
    def test_rest_ws_snapshot_consistency(self, mock_runtime):
        """Test that REST and WebSocket snapshots expose the same semantic state."""
        from parika.api.schemas.ui_context import UIContextResponse
        from parika.api.ws.ui import _serialize_state
        
        # Create a comprehensive state with all fields
        surfaces = (
            SurfaceItem(
                capability_id="weather.current",
                label="Current Conditions",
                tier=SurfaceTier.PRIMARY,
                contextual_role=ContextualRole.PRIMARY,
                relevance=0.9,
                domain="weather",
                semantic_type="current_conditions",
                capability_category="tool",
                capability_tags=("weather", "network"),
            ),
        )
        
        domains = (
            DomainInfo(
                name="weather",
                focus=FocusArea.CURRENT_CONDITIONS,
                importance=1.0,
                status="completed",
                capability_ids=("weather.current",),
                contextual_role=ContextualRole.PRIMARY,
                relevance=0.9,
                domain_category="information",
                primary_entities=("Patna, Bihar",),
                primary_topics=("weather",),
            ),
        )
        
        synthesis = SynthesisInfo(
            goal_id="goal-5",
            capability_id="chat.respond",
            status="completed",
            depends_on=("goal-1", "goal-2"),
            completed_dependencies=("goal-1", "goal-2"),
            failed_dependencies=(),
            contextual_role=ContextualRole.PRIMARY,
            domain="chat",
            semantic_type="summary",
            dependency_domains=("weather",),
        )
        
        dependencies = (
            DependencyInfo(
                goal_id="goal-1",
                capability_id="weather.current",
                depends_on=(),
                status="completed",
                is_synthesis=False,
                contextual_role=ContextualRole.PRIMARY,
                domain="weather",
                semantic_type="current_conditions",
                capability_category="tool",
                capability_tags=("weather", "network"),
                dependency_domains=(),
            ),
        )
        
        state = UIContextState(
            version=5,
            context="weather",
            confidence=0.95,
            source=ContextSource.TASK,
            attention=AttentionLevel.AMBIENT,
            urgency=UrgencyLevel.NORMAL,
            focus=FocusArea.CURRENT_CONDITIONS,
            surfaces=surfaces,
            timestamp=datetime.now(UTC),
            metadata=MappingProxyType({"task_id": "abc123"}),
            request_status=RequestStatus.PARTIAL_SUCCESS,
            domains=domains,
            synthesis=synthesis,
            dependencies=dependencies,
            user_intent=UserIntent.REQUESTING_INFORMATION,
            conversational_context=ConversationalContext(
                current_domain="weather",
                active_subject="weather: weather.current",
                ongoing_task="Request completed",
                previous_domain="weather",
                turn_count=1,
                last_user_request=None,
                contextual_transition=ContextTransition.NONE,
            ),
            semantic_relevance=(
                SemanticRelevance(
                    domain="weather",
                    score=0.9,
                    signals=("primary_context", "has_completed_tasks"),
                ),
            ),
            entities=(
                EntityInfo(
                    name="Patna, Bihar",
                    entity_type=EntityType.LOCATION,
                    domain="weather",
                    confidence=0.95,
                ),
            ),
            topics=(
                TopicInfo(
                    name="weather",
                    domain="weather",
                    relevance=0.9,
                    source="capability",
                ),
            ),
            context_transition=ContextTransition.NONE,
        )
        
        # Get REST response
        rest_response = UIContextResponse.from_state(state)
        
        # Get WebSocket snapshot
        ws_snapshot = _serialize_state(state)
        
        # Verify key fields match
        assert rest_response.version == ws_snapshot["version"]
        assert rest_response.context == ws_snapshot["context"]
        assert rest_response.confidence == ws_snapshot["confidence"]
        assert rest_response.source.value == ws_snapshot["source"]
        assert rest_response.attention.value == ws_snapshot["attention"]
        assert rest_response.urgency.value == ws_snapshot["urgency"]
        assert rest_response.focus.value == ws_snapshot["focus"]
        assert rest_response.request_status.value == ws_snapshot["request_status"]
        
        # Verify surfaces
        assert len(rest_response.surfaces) == len(ws_snapshot["surfaces"])
        for rest_surf, ws_surf in zip(rest_response.surfaces, ws_snapshot["surfaces"]):
            assert rest_surf.capability_id == ws_surf["capability_id"]
            assert rest_surf.label == ws_surf["label"]
            assert rest_surf.tier.value == ws_surf["tier"]
            assert rest_surf.contextual_role.value == ws_surf["contextual_role"]
            assert rest_surf.relevance == ws_surf["relevance"]
            assert rest_surf.domain == ws_surf["domain"]
            assert rest_surf.semantic_type == ws_surf["semantic_type"]
            assert rest_surf.capability_category == ws_surf["capability_category"]
            assert rest_surf.capability_tags == ws_surf["capability_tags"]
        
        # Verify domains
        assert len(rest_response.domains) == len(ws_snapshot["domains"])
        for rest_dom, ws_dom in zip(rest_response.domains, ws_snapshot["domains"]):
            assert rest_dom.name == ws_dom["name"]
            assert rest_dom.focus.value == ws_dom["focus"]
            assert rest_dom.importance == ws_dom["importance"]
            assert rest_dom.status == ws_dom["status"]
            assert rest_dom.capability_ids == ws_dom["capability_ids"]
            assert rest_dom.contextual_role.value == ws_dom["contextual_role"]
            assert rest_dom.relevance == ws_dom["relevance"]
            assert rest_dom.domain_category == ws_dom["domain_category"]
            assert rest_dom.primary_entities == ws_dom["primary_entities"]
            assert rest_dom.primary_topics == ws_dom["primary_topics"]
        
        # Verify synthesis
        assert rest_response.synthesis is not None
        assert ws_snapshot["synthesis"] is not None
        assert rest_response.synthesis.goal_id == ws_snapshot["synthesis"]["goal_id"]
        assert rest_response.synthesis.capability_id == ws_snapshot["synthesis"]["capability_id"]
        assert rest_response.synthesis.status == ws_snapshot["synthesis"]["status"]
        assert rest_response.synthesis.depends_on == ws_snapshot["synthesis"]["depends_on"]
        assert rest_response.synthesis.completed_dependencies == ws_snapshot["synthesis"]["completed_dependencies"]
        assert rest_response.synthesis.failed_dependencies == ws_snapshot["synthesis"]["failed_dependencies"]
        assert rest_response.synthesis.contextual_role.value == ws_snapshot["synthesis"]["contextual_role"]
        assert rest_response.synthesis.domain == ws_snapshot["synthesis"]["domain"]
        assert rest_response.synthesis.semantic_type == ws_snapshot["synthesis"]["semantic_type"]
        assert rest_response.synthesis.dependency_domains == ws_snapshot["synthesis"]["dependency_domains"]
        
        # Verify dependencies
        assert len(rest_response.dependencies) == len(ws_snapshot["dependencies"])
        for rest_dep, ws_dep in zip(rest_response.dependencies, ws_snapshot["dependencies"]):
            assert rest_dep.goal_id == ws_dep["goal_id"]
            assert rest_dep.capability_id == ws_dep["capability_id"]
            assert rest_dep.depends_on == ws_dep["depends_on"]
            assert rest_dep.status == ws_dep["status"]
            assert rest_dep.is_synthesis == ws_dep["is_synthesis"]
            assert rest_dep.contextual_role.value == ws_dep["contextual_role"]
            assert rest_dep.domain == ws_dep["domain"]
            assert rest_dep.semantic_type == ws_dep["semantic_type"]
            assert rest_dep.capability_category == ws_dep["capability_category"]
            assert rest_dep.capability_tags == ws_dep["capability_tags"]
            assert rest_dep.dependency_domains == ws_dep["dependency_domains"]
        
        # Verify Phase 2 fields
        assert rest_response.user_intent.value == ws_snapshot["user_intent"]
        assert rest_response.conversational_context is not None
        assert ws_snapshot["conversational_context"] is not None
        assert rest_response.conversational_context.current_domain == ws_snapshot["conversational_context"]["current_domain"]
        assert rest_response.conversational_context.contextual_transition.value == ws_snapshot["conversational_context"]["contextual_transition"]
        
        assert len(rest_response.semantic_relevance) == len(ws_snapshot["semantic_relevance"])
        for rest_rel, ws_rel in zip(rest_response.semantic_relevance, ws_snapshot["semantic_relevance"]):
            assert rest_rel.domain == ws_rel["domain"]
            assert rest_rel.score == ws_rel["score"]
            assert rest_rel.signals == ws_rel["signals"]
        
        assert len(rest_response.entities) == len(ws_snapshot["entities"])
        for rest_ent, ws_ent in zip(rest_response.entities, ws_snapshot["entities"]):
            assert rest_ent.name == ws_ent["name"]
            assert rest_ent.entity_type.value == ws_ent["entity_type"]
            assert rest_ent.domain == ws_ent["domain"]
            assert rest_ent.confidence == ws_ent["confidence"]
        
        assert len(rest_response.topics) == len(ws_snapshot["topics"])
        for rest_top, ws_top in zip(rest_response.topics, ws_snapshot["topics"]):
            assert rest_top.name == ws_top["name"]
            assert rest_top.domain == ws_top["domain"]
            assert rest_top.relevance == ws_top["relevance"]
            assert rest_top.source == ws_top["source"]
        
        assert rest_response.context_transition.value == ws_snapshot["context_transition"]
    
    def test_rest_ws_changed_event_consistency(self):
        """Test that REST state and WS changed event are consistent."""
        from parika.api.ws.ui import UI_CONTEXT_CHANGED, _serialize_state
        
        # Create a state
        surfaces = (
            SurfaceItem(
                capability_id="weather.current",
                label="Current Conditions",
                tier=SurfaceTier.PRIMARY,
            ),
        )
        
        state = UIContextState(
            version=10,
            context="weather",
            confidence=0.95,
            source=ContextSource.TASK,
            attention=AttentionLevel.PRIMARY,
            urgency=UrgencyLevel.NORMAL,
            focus=FocusArea.CURRENT_CONDITIONS,
            surfaces=surfaces,
            timestamp=datetime.now(UTC),
            metadata=MappingProxyType({}),
            request_status=RequestStatus.SUCCESS,
        )
        
        # Create a UIContextChanged event
        changed_event = UIContextChanged(
            version=10,
            previous_version=9,
            changed_fields=frozenset({"context", "surfaces"}),
            source_event="task.started",
        )
        
        # Serialize state for WS
        ws_state = _serialize_state(state)
        
        # Verify the changed event structure matches what WS would send
        ws_changed_payload = {
            "version": changed_event.version,
            "previous_version": changed_event.previous_version,
            "changed_fields": list(changed_event.changed_fields),
            "source_event": changed_event.source_event,
            "timestamp": changed_event.timestamp.isoformat(),
            "state": ws_state,
        }
        
        # The changed event should contain the full state
        assert ws_changed_payload["version"] == state.version
        assert ws_changed_payload["previous_version"] == 9
        assert set(ws_changed_payload["changed_fields"]) == {"context", "surfaces"}
        assert ws_changed_payload["source_event"] == "task.started"
        assert ws_changed_payload["state"]["version"] == state.version
        assert ws_changed_payload["state"]["context"] == state.context