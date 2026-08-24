"""
PARIKA API - UI Context Schemas

Wire-format Pydantic schemas for the UI Context REST endpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .common import ApiModel
from parika.core.ui_context.state import (
    AttentionLevel,
    ContextSource,
    ContextTransition,
    ContextualRole,
    DependencyInfo,
    DomainInfo,
    EntityInfo,
    EntityType,
    FocusArea,
    FreshnessInfo,
    RequestStatus,
    SemanticRelevance,
    SurfaceItem,
    SurfaceTier,
    SynthesisInfo,
    TopicInfo,
    UIContextState,
    UrgencyLevel,
    UserIntent,
    ConversationalContext,
)


class FreshnessInfoSchema(ApiModel):
    """Wire-format freshness info."""
    
    domain: str
    last_updated: datetime | None = None
    status: str
    max_age_seconds: float | None = None


class EntityInfoSchema(ApiModel):
    """Wire-format entity info."""
    
    name: str
    entity_type: EntityType
    domain: str
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TopicInfoSchema(ApiModel):
    """Wire-format topic info."""
    
    name: str
    domain: str
    relevance: float = Field(ge=0.0, le=1.0)
    source: str


class ConversationalContextSchema(ApiModel):
    """Wire-format conversational context."""
    
    current_domain: str | None = None
    active_subject: str | None = None
    ongoing_task: str | None = None
    previous_domain: str | None = None
    turn_count: int = 0
    last_user_request: str | None = None
    contextual_transition: ContextTransition = ContextTransition.NONE


class SemanticRelevanceSchema(ApiModel):
    """Wire-format semantic relevance."""
    
    domain: str
    score: float = Field(ge=0.0, le=1.0)
    signals: list[str] = Field(default_factory=list)


class SurfaceItemSchema(ApiModel):
    """Wire-format surface item."""
    
    capability_id: str
    label: str
    tier: SurfaceTier
    contextual_role: ContextualRole = ContextualRole.PRIMARY
    relevance: float = Field(default=1.0, ge=0.0, le=1.0)
    freshness: FreshnessInfoSchema | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    # Phase 3: Semantic decoupling fields
    domain: str | None = None
    semantic_type: str | None = None
    capability_category: str | None = None
    capability_tags: list[str] = Field(default_factory=list)


class DomainInfoSchema(ApiModel):
    """Wire-format domain info."""
    
    name: str
    focus: FocusArea
    importance: float = Field(ge=0.0, le=1.0)
    status: str
    capability_ids: list[str]
    contextual_role: ContextualRole = ContextualRole.PRIMARY
    relevance: float = Field(default=1.0, ge=0.0, le=1.0)
    entities: list[EntityInfoSchema] = Field(default_factory=list)
    topics: list[TopicInfoSchema] = Field(default_factory=list)
    freshness: FreshnessInfoSchema | None = None
    
    # Phase 3: Semantic decoupling fields
    domain_category: str | None = None
    primary_entities: list[str] = Field(default_factory=list)
    primary_topics: list[str] = Field(default_factory=list)


class SynthesisInfoSchema(ApiModel):
    """Wire-format synthesis info."""
    
    goal_id: str | None = None
    capability_id: str | None = None
    status: str
    depends_on: list[str] = Field(default_factory=list)
    completed_dependencies: list[str] = Field(default_factory=list)
    failed_dependencies: list[str] = Field(default_factory=list)
    contextual_role: ContextualRole = ContextualRole.PRIMARY
    
    # Phase 3: Semantic decoupling fields
    domain: str | None = None
    semantic_type: str | None = None
    dependency_domains: list[str] = Field(default_factory=list)


class DependencyInfoSchema(ApiModel):
    """Wire-format dependency info."""
    
    goal_id: str
    capability_id: str
    depends_on: list[str] = Field(default_factory=list)
    status: str
    is_synthesis: bool
    contextual_role: ContextualRole = ContextualRole.PRIMARY
    
    # Phase 3: Semantic decoupling fields
    domain: str | None = None
    semantic_type: str | None = None
    capability_category: str | None = None
    capability_tags: list[str] = Field(default_factory=list)
    dependency_domains: list[str] = Field(default_factory=list)


class UIContextResponse(ApiModel):
    """Wire-format UI context response."""
    
    version: int
    context: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: ContextSource
    attention: AttentionLevel
    urgency: UrgencyLevel
    focus: FocusArea
    surfaces: list[SurfaceItemSchema]
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    request_status: RequestStatus
    domains: list[DomainInfoSchema] = Field(default_factory=list)
    synthesis: SynthesisInfoSchema | None = None
    dependencies: list[DependencyInfoSchema] = Field(default_factory=list)
    
    # Phase 2 fields
    user_intent: UserIntent = UserIntent.UNKNOWN
    conversational_context: ConversationalContextSchema | None = None
    semantic_relevance: list[SemanticRelevanceSchema] = Field(default_factory=list)
    entities: list[EntityInfoSchema] = Field(default_factory=list)
    topics: list[TopicInfoSchema] = Field(default_factory=list)
    context_transition: ContextTransition = ContextTransition.NONE
    
    @classmethod
    def from_state(cls, state: UIContextState) -> "UIContextResponse":
        """Create response from UIContextState."""
        return cls(
            version=state.version,
            context=state.context,
            confidence=state.confidence,
            source=state.source,
            attention=state.attention,
            urgency=state.urgency,
            focus=state.focus,
            surfaces=[
                SurfaceItemSchema(
                    capability_id=surface.capability_id,
                    label=surface.label,
                    tier=surface.tier,
                    contextual_role=surface.contextual_role,
                    relevance=surface.relevance,
                    freshness=FreshnessInfoSchema(
                        domain=surface.freshness.domain,
                        last_updated=surface.freshness.last_updated,
                        status=surface.freshness.status,
                        max_age_seconds=surface.freshness.max_age_seconds,
                    ) if surface.freshness else None,
                    metadata=dict(surface.metadata),
                    domain=surface.domain,
                    semantic_type=surface.semantic_type,
                    capability_category=surface.capability_category,
                    capability_tags=list(surface.capability_tags),
                )
                for surface in state.surfaces
            ],
            timestamp=state.timestamp,
            metadata=dict(state.metadata),
            request_status=state.request_status,
            domains=[
                DomainInfoSchema(
                    name=domain.name,
                    focus=domain.focus,
                    importance=domain.importance,
                    status=domain.status,
                    capability_ids=list(domain.capability_ids),
                    contextual_role=domain.contextual_role,
                    relevance=domain.relevance,
                    entities=[EntityInfoSchema(
                        name=e.name,
                        entity_type=e.entity_type,
                        domain=e.domain,
                        confidence=e.confidence,
                        metadata=dict(e.metadata),
                    ) for e in domain.entities],
                    topics=[TopicInfoSchema(
                        name=t.name,
                        domain=t.domain,
                        relevance=t.relevance,
                        source=t.source,
                    ) for t in domain.topics],
                    freshness=FreshnessInfoSchema(
                        domain=domain.freshness.domain,
                        last_updated=domain.freshness.last_updated,
                        status=domain.freshness.status,
                        max_age_seconds=domain.freshness.max_age_seconds,
                    ) if domain.freshness else None,
                    domain_category=domain.domain_category,
                    primary_entities=list(domain.primary_entities),
                    primary_topics=list(domain.primary_topics),
                )
                for domain in state.domains
            ],
            synthesis=(
                SynthesisInfoSchema(
                    goal_id=state.synthesis.goal_id,
                    capability_id=state.synthesis.capability_id,
                    status=state.synthesis.status,
                    depends_on=list(state.synthesis.depends_on),
                    completed_dependencies=list(state.synthesis.completed_dependencies),
                    failed_dependencies=list(state.synthesis.failed_dependencies),
                    contextual_role=state.synthesis.contextual_role,
                    domain=state.synthesis.domain,
                    semantic_type=state.synthesis.semantic_type,
                    dependency_domains=list(state.synthesis.dependency_domains),
                )
                if state.synthesis else None
            ),
            dependencies=[
                DependencyInfoSchema(
                    goal_id=dep.goal_id,
                    capability_id=dep.capability_id,
                    depends_on=list(dep.depends_on),
                    status=dep.status,
                    is_synthesis=dep.is_synthesis,
                    contextual_role=dep.contextual_role,
                    domain=dep.domain,
                    semantic_type=dep.semantic_type,
                    capability_category=dep.capability_category,
                    capability_tags=list(dep.capability_tags),
                    dependency_domains=list(dep.dependency_domains),
                )
                for dep in state.dependencies
            ],
            user_intent=state.user_intent,
            conversational_context=(
                ConversationalContextSchema(
                    current_domain=state.conversational_context.current_domain,
                    active_subject=state.conversational_context.active_subject,
                    ongoing_task=state.conversational_context.ongoing_task,
                    previous_domain=state.conversational_context.previous_domain,
                    turn_count=state.conversational_context.turn_count,
                    last_user_request=state.conversational_context.last_user_request,
                    contextual_transition=state.conversational_context.contextual_transition,
                )
                if state.conversational_context else None
            ),
            semantic_relevance=[
                SemanticRelevanceSchema(
                    domain=rel.domain,
                    score=rel.score,
                    signals=list(rel.signals),
                )
                for rel in state.semantic_relevance
            ],
            entities=[
                EntityInfoSchema(
                    name=e.name,
                    entity_type=e.entity_type,
                    domain=e.domain,
                    confidence=e.confidence,
                    metadata=dict(e.metadata),
                )
                for e in state.entities
            ],
            topics=[
                TopicInfoSchema(
                    name=t.name,
                    domain=t.domain,
                    relevance=t.relevance,
                    source=t.source,
                )
                for t in state.topics
            ],
            context_transition=state.context_transition,
        )