"""
PARIKA UI Context State Models.

Immutable semantic snapshot for server-side contextual HUD.
Contains NO visual rendering logic - only semantic meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class ContextSource(StrEnum):
    """
    Source of the current semantic context.
    
    Represents WHY the current semantic context was selected.
    """
    
    CAPABILITY = "capability"
    WORKFLOW = "workflow"
    TASK = "task"
    INTERACTION = "interaction"
    SYSTEM = "system"
    FALLBACK = "fallback"


class AttentionLevel(StrEnum):
    """
    Attention level independent from semantic context.
    
    Conceptually: primary, secondary, ambient
    """
    
    PRIMARY = "primary"
    SECONDARY = "secondary"
    AMBIENT = "ambient"


class UrgencyLevel(StrEnum):
    """
    Urgency level independent from context.
    
    Conceptually: normal, elevated, critical
    """
    
    NORMAL = "normal"
    ELEVATED = "elevated"
    CRITICAL = "critical"


class RequestStatus(StrEnum):
    """
    Overall request-level status.
    
    Mirrors BrainResponse.RequestStatus for semantic consistency.
    """
    
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"


class FocusArea(StrEnum):
    """
    Semantic sub-context focus areas.
    
    Examples:
    - weather -> forecast, current_conditions
    - expense -> monthly_summary
    - media -> playback
    - chat -> general
    """
    
    GENERAL = "general"
    FORECAST = "forecast"
    CURRENT_CONDITIONS = "current_conditions"
    MONTHLY_SUMMARY = "monthly_summary"
    PLAYBACK = "playback"
    SEARCH_RESULTS = "search_results"
    FILE_BROWSER = "file_browser"
    CODE_EDITOR = "code_editor"
    DOCUMENT_VIEWER = "document_viewer"
    IMAGE_VIEWER = "image_viewer"
    VIDEO_PLAYER = "video_player"
    VOICE_INPUT = "voice_input"
    SETTINGS = "settings"
    HELP = "help"
    SYNTHESIS = "synthesis"


class SurfaceTier(StrEnum):
    """
    Semantic surface tiers.
    
    Primary: Main capabilities/information for current context
    Secondary: Supporting capabilities/information
    Ambient: Background/system information
    """
    
    PRIMARY = "primary"
    SECONDARY = "secondary"
    AMBIENT = "ambient"


class ContextualRole(StrEnum):
    """
    Contextual role of a surface/domain in the current HUD.
    
    PRIMARY: The main focus of current interaction
    SECONDARY: Supporting information for the primary task
    AMBIENT: Background context that persists but is not the focus
    """
    
    PRIMARY = "primary"
    SECONDARY = "secondary"
    AMBIENT = "ambient"


class UserIntent(StrEnum):
    """
    High-level user intent derived from execution state.
    
    Derived deterministically from goal/capability patterns,
    NOT from LLM classification.
    """
    
    REQUESTING_INFORMATION = "requesting_information"
    MONITORING = "monitoring"
    EXECUTING_ACTION = "executing_action"
    CREATING = "creating"
    RESEARCHING = "researching"
    COMMUNICATING = "communicating"
    UNKNOWN = "unknown"


class EntityType(StrEnum):
    """
    Type of entity extracted from context.
    
    Represents structured entities known to PARIKA.
    """
    
    LOCATION = "location"
    CURRENCY = "currency"
    DATE_TIME = "date_time"
    PERSON = "person"
    ORGANIZATION = "organization"
    EVENT = "event"
    TOPIC = "topic"
    MEASUREMENT = "measurement"
    UNKNOWN = "unknown"


class ContextTransition(StrEnum):
    """
    Type of context transition between turns.
    """
    
    ENTERED = "entered"
    CHANGED = "changed"
    EXPANDED = "expanded"
    NARROWED = "narrowed"
    BECAME_AMBIENT = "became_ambient"
    NONE = "none"


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityInfo:
    """
    Structured entity information.
    
    Represents an entity known in the current context.
    """
    
    name: str
    """Entity name (e.g., 'Patna', 'USD', 'Jharkhand protest')"""
    
    entity_type: EntityType
    """Type of entity"""
    
    domain: str
    """Domain this entity belongs to (e.g., 'weather', 'finance', 'news')"""
    
    confidence: float
    """Confidence this entity is relevant (0.0 to 1.0)"""
    
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Additional entity metadata (e.g., coordinates for location)"""
    
    def __post_init__(self) -> None:
        """Validate entity info after initialization."""
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if type(self.entity_type) is not EntityType:
            raise TypeError("entity_type must be an EntityType")
        if type(self.domain) is not str or not self.domain.strip():
            raise ValueError("domain must be a non-empty string")
        if type(self.confidence) is not float:
            raise TypeError("confidence must be a float")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        if type(self.metadata) is not MappingProxyType:
            raise TypeError("metadata must be a MappingProxyType")
        
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TopicInfo:
    """
    Topic/subject information for contextual understanding.
    
    Represents a semantic subject, not implementation details.
    """
    
    name: str
    """Topic name (e.g., 'weather', 'finance', 'current_events', 'coding')"""
    
    domain: str
    """Associated domain"""
    
    relevance: float
    """Relevance score (0.0 to 1.0)"""
    
    source: str
    """Source of topic: 'capability', 'goal', 'conversation', 'memory', 'knowledge'"""
    
    def __post_init__(self) -> None:
        """Validate topic info after initialization."""
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if type(self.domain) is not str or not self.domain.strip():
            raise ValueError("domain must be a non-empty string")
        if type(self.relevance) is not float:
            raise TypeError("relevance must be a float")
        if not (0.0 <= self.relevance <= 1.0):
            raise ValueError("relevance must be between 0.0 and 1.0")
        if type(self.source) is not str:
            raise TypeError("source must be a string")


@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationalContext:
    """
    Conversational continuity information.
    
    Tracks context evolution across turns without exposing raw history.
    """
    
    current_domain: str | None
    """Current primary conversational domain"""
    
    active_subject: str | None
    """Active subject of conversation (e.g., 'weather in Patna')"""
    
    ongoing_task: str | None
    """Ongoing task description if any"""
    
    previous_domain: str | None
    """Previous turn's primary domain"""
    
    turn_count: int
    """Number of turns in current context session"""
    
    last_user_request: str | None
    """Last user request text (truncated)"""
    
    contextual_transition: ContextTransition = ContextTransition.NONE
    """Type of context transition from previous turn"""
    
    def __post_init__(self) -> None:
        """Validate conversational context after initialization."""
        if self.current_domain is not None and (type(self.current_domain) is not str or not self.current_domain.strip()):
            raise ValueError("current_domain must be a non-empty string or None")
        if self.active_subject is not None and (type(self.active_subject) is not str or not self.active_subject.strip()):
            raise ValueError("active_subject must be a non-empty string or None")
        if self.ongoing_task is not None and (type(self.ongoing_task) is not str or not self.ongoing_task.strip()):
            raise ValueError("ongoing_task must be a non-empty string or None")
        if self.previous_domain is not None and (type(self.previous_domain) is not str or not self.previous_domain.strip()):
            raise ValueError("previous_domain must be a non-empty string or None")
        if type(self.turn_count) is not int:
            raise TypeError("turn_count must be an integer")
        if self.turn_count < 0:
            raise ValueError("turn_count must be non-negative")
        if self.last_user_request is not None and type(self.last_user_request) is not str:
            raise TypeError("last_user_request must be a string or None")
        if type(self.contextual_transition) is not ContextTransition:
            raise TypeError("contextual_transition must be a ContextTransition")


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticRelevance:
    """
    Semantic relevance scoring for domains/surfaces.
    
    Based on deterministic signals, not arbitrary scores.
    """
    
    domain: str
    """Domain name"""
    
    score: float
    """Relevance score (0.0 to 1.0)"""
    
    signals: tuple[str, ...]
    """Signals that contributed to this score"""
    
    def __post_init__(self) -> None:
        """Validate semantic relevance after initialization."""
        if type(self.domain) is not str or not self.domain.strip():
            raise ValueError("domain must be a non-empty string")
        if type(self.score) is not float:
            raise TypeError("score must be a float")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError("score must be between 0.0 and 1.0")
        if type(self.signals) is not tuple:
            raise TypeError("signals must be a tuple")
        for signal in self.signals:
            if type(signal) is not str:
                raise TypeError("each signal must be a string")


@dataclass(frozen=True, slots=True, kw_only=True)
class FreshnessInfo:
    """
    Freshness information for time-sensitive domains.
    
    Uses existing timestamps, does not create new caching.
    """
    
    domain: str
    """Domain name"""
    
    last_updated: datetime | None
    """When this domain's information was last retrieved"""
    
    status: str
    """Freshness status: 'fresh', 'recent', 'stale', 'unavailable'"""
    
    max_age_seconds: float | None
    """Maximum age for this domain to be considered fresh"""
    
    def __post_init__(self) -> None:
        """Validate freshness info after initialization."""
        if type(self.domain) is not str or not self.domain.strip():
            raise ValueError("domain must be a non-empty string")
        if self.last_updated is not None and type(self.last_updated) is not datetime:
            raise TypeError("last_updated must be a datetime or None")
        if type(self.status) is not str:
            raise TypeError("status must be a string")
        if self.max_age_seconds is not None and type(self.max_age_seconds) is not float:
            raise TypeError("max_age_seconds must be a float or None")


@dataclass(frozen=True, slots=True, kw_only=True)
class SurfaceItem:
    """
    Semantic surface item.
    
    Represents a capability or information element relevant to the current context.
    MUST remain semantic - no visual rendering instructions.
    """
    
    capability_id: str
    """Capability identifier (e.g., 'weather.current', 'weather.forecast')"""
    
    label: str
    """Human-readable label for the surface"""
    
    tier: SurfaceTier
    """Semantic tier: primary, secondary, or ambient"""
    
    contextual_role: ContextualRole = ContextualRole.PRIMARY
    """Role in current contextual HUD"""
    
    relevance: float = 1.0
    """Semantic relevance to current context (0.0 to 1.0)"""
    
    freshness: FreshnessInfo | None = None
    """Freshness information if applicable"""
    
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Optional semantic metadata"""
    
    # Phase 3: Semantic decoupling fields (additive for backward compatibility)
    domain: str | None = None
    """Semantic domain (e.g., 'weather', 'finance', 'search') - derived from capability"""
    
    semantic_type: str | None = None
    """Semantic type within domain (e.g., 'current_conditions', 'forecast', 'exchange_rate')"""
    
    capability_category: str | None = None
    """Capability category (e.g., 'tool', 'llm', 'speech')"""
    
    capability_tags: tuple[str, ...] = field(default_factory=tuple)
    """Capability tags for semantic grouping"""

    def __post_init__(self) -> None:
        """Validate surface item after initialization."""
        if not self.capability_id.strip():
            raise ValueError("capability_id cannot be empty")
        if not self.label.strip():
            raise ValueError("label cannot be empty")
        if type(self.tier) is not SurfaceTier:
            raise TypeError("tier must be a SurfaceTier")
        if type(self.contextual_role) is not ContextualRole:
            raise TypeError("contextual_role must be a ContextualRole")
        if type(self.relevance) is not float:
            raise TypeError("relevance must be a float")
        if not (0.0 <= self.relevance <= 1.0):
            raise ValueError("relevance must be between 0.0 and 1.0")
        if self.freshness is not None and type(self.freshness) is not FreshnessInfo:
            raise TypeError("freshness must be a FreshnessInfo or None")
        if type(self.metadata) is not MappingProxyType:
            raise TypeError("metadata must be a MappingProxyType")
        if self.domain is not None and (type(self.domain) is not str or not self.domain.strip()):
            raise ValueError("domain must be a non-empty string or None")
        if self.semantic_type is not None and (type(self.semantic_type) is not str or not self.semantic_type.strip()):
            raise ValueError("semantic_type must be a non-empty string or None")
        if self.capability_category is not None and (type(self.capability_category) is not str or not self.capability_category.strip()):
            raise ValueError("capability_category must be a non-empty string or None")
        if type(self.capability_tags) is not tuple:
            raise TypeError("capability_tags must be a tuple")
        for tag in self.capability_tags:
            if type(tag) is not str:
                raise TypeError("each capability_tag must be a string")
        
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainInfo:
    """
    Semantic domain information for multi-domain context.
    
    Represents a contextual domain active in the current request.
    """
    
    name: str
    """Domain name (e.g., 'weather', 'finance', 'news')"""
    
    focus: FocusArea
    """Primary focus area within this domain"""
    
    importance: float
    """Relative importance (0.0 to 1.0)"""
    
    status: str
    """Execution status: 'running', 'waiting', 'completed', 'failed'"""
    
    capability_ids: tuple[str, ...]
    """Capability IDs associated with this domain"""
    
    contextual_role: ContextualRole = ContextualRole.PRIMARY
    """Role in current contextual HUD"""
    
    relevance: float = 1.0
    """Semantic relevance to current context (0.0 to 1.0)"""
    
    entities: tuple[EntityInfo, ...] = field(default_factory=tuple)
    """Entities associated with this domain"""
    
    topics: tuple[TopicInfo, ...] = field(default_factory=tuple)
    """Topics associated with this domain"""
    
    freshness: FreshnessInfo | None = None
    """Freshness information if applicable"""
    
    # Phase 3: Semantic decoupling fields
    domain_category: str | None = None
    """Semantic category of this domain (e.g., 'information', 'action', 'communication')"""
    
    primary_entities: tuple[str, ...] = field(default_factory=tuple)
    """Primary entity names for quick client access"""
    
    primary_topics: tuple[str, ...] = field(default_factory=tuple)
    """Primary topic names for quick client access"""
    
    def __post_init__(self) -> None:
        """Validate domain info after initialization."""
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if type(self.focus) is not FocusArea:
            raise TypeError("focus must be a FocusArea")
        if type(self.importance) is not float:
            raise TypeError("importance must be a float")
        if not (0.0 <= self.importance <= 1.0):
            raise ValueError("importance must be between 0.0 and 1.0")
        if type(self.status) is not str:
            raise TypeError("status must be a string")
        if type(self.capability_ids) is not tuple:
            raise TypeError("capability_ids must be a tuple")
        if type(self.contextual_role) is not ContextualRole:
            raise TypeError("contextual_role must be a ContextualRole")
        if type(self.relevance) is not float:
            raise TypeError("relevance must be a float")
        if not (0.0 <= self.relevance <= 1.0):
            raise ValueError("relevance must be between 0.0 and 1.0")
        if type(self.entities) is not tuple:
            raise TypeError("entities must be a tuple")
        for entity in self.entities:
            if type(entity) is not EntityInfo:
                raise TypeError("each entity must be an EntityInfo")
        if type(self.topics) is not tuple:
            raise TypeError("topics must be a tuple")
        for topic in self.topics:
            if type(topic) is not TopicInfo:
                raise TypeError("each topic must be a TopicInfo")
        if self.freshness is not None and type(self.freshness) is not FreshnessInfo:
            raise TypeError("freshness must be a FreshnessInfo or None")
        if self.domain_category is not None and (type(self.domain_category) is not str or not self.domain_category.strip()):
            raise ValueError("domain_category must be a non-empty string or None")
        if type(self.primary_entities) is not tuple:
            raise TypeError("primary_entities must be a tuple")
        for e in self.primary_entities:
            if type(e) is not str:
                raise TypeError("each primary_entity must be a string")
        if type(self.primary_topics) is not tuple:
            raise TypeError("primary_topics must be a tuple")
        for t in self.primary_topics:
            if type(t) is not str:
                raise TypeError("each primary_topic must be a string")


@dataclass(frozen=True, slots=True, kw_only=True)
class SynthesisInfo:
    """
    Synthesis goal information.
    
    Represents the synthesis activity in a multi-goal request.
    """
    
    goal_id: str | None
    """Synthesis goal identifier"""
    
    capability_id: str | None
    """Synthesis capability ID (typically 'chat.respond')"""
    
    status: str
    """Synthesis status: 'pending', 'waiting', 'running', 'completed', 'failed'"""
    
    depends_on: tuple[str, ...]
    """Goal IDs this synthesis depends on"""
    
    completed_dependencies: tuple[str, ...]
    """Goal IDs of completed dependencies"""
    
    failed_dependencies: tuple[str, ...]
    """Goal IDs of failed dependencies"""
    
    contextual_role: ContextualRole = ContextualRole.PRIMARY
    """Role in current contextual HUD"""
    
    # Phase 3: Semantic decoupling fields
    domain: str | None = None
    """Semantic domain of synthesis (e.g., 'chat', 'report_generation')"""
    
    semantic_type: str | None = None
    """Type of synthesis (e.g., 'summary', 'report', 'answer', 'aggregation')"""
    
    dependency_domains: tuple[str, ...] = field(default_factory=tuple)
    """Domains of the dependencies"""
    
    def __post_init__(self) -> None:
        """Validate synthesis info after initialization."""
        if self.goal_id is not None and type(self.goal_id) is not str:
            raise TypeError("goal_id must be a string or None")
        if self.capability_id is not None and type(self.capability_id) is not str:
            raise TypeError("capability_id must be a string or None")
        if type(self.status) is not str:
            raise TypeError("status must be a string")
        if type(self.depends_on) is not tuple:
            raise TypeError("depends_on must be a tuple")
        if type(self.completed_dependencies) is not tuple:
            raise TypeError("completed_dependencies must be a tuple")
        if type(self.failed_dependencies) is not tuple:
            raise TypeError("failed_dependencies must be a tuple")
        if type(self.contextual_role) is not ContextualRole:
            raise TypeError("contextual_role must be a ContextualRole")
        if self.domain is not None and (type(self.domain) is not str or not self.domain.strip()):
            raise ValueError("domain must be a non-empty string or None")
        if self.semantic_type is not None and (type(self.semantic_type) is not str or not self.semantic_type.strip()):
            raise ValueError("semantic_type must be a non-empty string or None")
        if type(self.dependency_domains) is not tuple:
            raise TypeError("dependency_domains must be a tuple")
        for d in self.dependency_domains:
            if type(d) is not str:
                raise TypeError("each dependency_domain must be a string")


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyInfo:
    """
    Dependency relationship information.
    
    Represents the dependency graph between goals.
    """
    
    goal_id: str
    """Goal identifier"""
    
    capability_id: str
    """Capability ID for this goal"""
    
    depends_on: tuple[str, ...]
    """Goal IDs this goal depends on"""
    
    status: str
    """Goal status: 'pending', 'waiting', 'running', 'completed', 'failed', 'skipped'"""
    
    is_synthesis: bool
    """Whether this goal is a synthesis goal"""
    
    contextual_role: ContextualRole = ContextualRole.PRIMARY
    """Role in current contextual HUD"""
    
    # Phase 3: Semantic decoupling fields
    domain: str | None = None
    """Semantic domain (e.g., 'weather', 'finance', 'search')"""
    
    semantic_type: str | None = None
    """Semantic type within domain (e.g., 'current_conditions', 'exchange_rate')"""
    
    capability_category: str | None = None
    """Capability category (e.g., 'tool', 'llm', 'speech')"""
    
    capability_tags: tuple[str, ...] = field(default_factory=tuple)
    """Capability tags for semantic grouping"""
    
    dependency_domains: tuple[str, ...] = field(default_factory=tuple)
    """Domains of the dependencies"""
    
    def __post_init__(self) -> None:
        """Validate dependency info after initialization."""
        if type(self.goal_id) is not str or not self.goal_id.strip():
            raise ValueError("goal_id must be a non-empty string")
        if type(self.capability_id) is not str or not self.capability_id.strip():
            raise ValueError("capability_id must be a non-empty string")
        if type(self.depends_on) is not tuple:
            raise TypeError("depends_on must be a tuple")
        if type(self.status) is not str:
            raise TypeError("status must be a string")
        if type(self.is_synthesis) is not bool:
            raise TypeError("is_synthesis must be a bool")
        if type(self.contextual_role) is not ContextualRole:
            raise TypeError("contextual_role must be a ContextualRole")
        if self.domain is not None and (type(self.domain) is not str or not self.domain.strip()):
            raise ValueError("domain must be a non-empty string or None")
        if self.semantic_type is not None and (type(self.semantic_type) is not str or not self.semantic_type.strip()):
            raise ValueError("semantic_type must be a non-empty string or None")
        if self.capability_category is not None and (type(self.capability_category) is not str or not self.capability_category.strip()):
            raise ValueError("capability_category must be a non-empty string or None")
        if type(self.capability_tags) is not tuple:
            raise TypeError("capability_tags must be a tuple")
        for tag in self.capability_tags:
            if type(tag) is not str:
                raise TypeError("each capability_tag must be a string")
        if type(self.dependency_domains) is not tuple:
            raise TypeError("dependency_domains must be a tuple")
        for d in self.dependency_domains:
            if type(d) is not str:
                raise TypeError("each dependency_domain must be a string")


@dataclass(frozen=True, slots=True, kw_only=True)
class UIContextState:
    """
    Immutable semantic UI context snapshot.
    
    Server-side semantic state only - NO visual rendering logic.
    The Web Client interprets this state using PARIKA Visual Grammar.
    
    Attributes:
        version: Monotonically increasing semantic version
        context: Current semantic domain (e.g., 'weather', 'expense', 'chat')
        confidence: Context confidence (0.0 to 1.0)
        source: Why this context was selected
        attention: Current attention level (primary/secondary/ambient)
        urgency: Current urgency level (normal/elevated/critical)
        focus: Current semantic sub-context focus
        surfaces: Semantic capabilities/information organized by tier
        timestamp: UTC timestamp of this snapshot
        metadata: Additional semantic metadata
        request_status: Overall request-level status (success/partial_success/failed)
        domains: Multiple active semantic domains with importance
        synthesis: Synthesis goal information
        dependencies: Dependency relationships between goals
        
        # Phase 2 additions:
        user_intent: High-level user intent derived from execution state
        conversational_context: Conversational continuity across turns
        semantic_relevance: Relevance scores for active domains
        entities: Structured entities in current context
        topics: Semantic topics/subjects in current context
        context_transition: Transition type from previous turn
    """
    
    version: int
    """Monotonically increasing semantic version"""
    
    context: str
    """Current semantic domain (primary domain for backward compatibility)"""
    
    confidence: float
    """Context confidence (0.0 <= confidence <= 1.0)"""
    
    source: ContextSource
    """Source of the current semantic context"""
    
    attention: AttentionLevel
    """Current attention level"""
    
    urgency: UrgencyLevel
    """Current urgency level"""
    
    focus: FocusArea
    """Current semantic sub-context focus"""
    
    surfaces: tuple[SurfaceItem, ...]
    """Semantic capabilities/information organized by tier"""
    
    timestamp: datetime
    """UTC timestamp of this snapshot"""
    
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Additional semantic metadata"""
    
    request_status: RequestStatus = RequestStatus.FAILED
    """Overall request-level status"""
    
    domains: tuple[DomainInfo, ...] = field(default_factory=tuple)
    """Multiple active semantic domains with importance"""
    
    synthesis: SynthesisInfo | None = None
    """Synthesis goal information"""
    
    dependencies: tuple[DependencyInfo, ...] = field(default_factory=tuple)
    """Dependency relationships between goals"""
    
    # Phase 2 fields
    user_intent: UserIntent = UserIntent.UNKNOWN
    """High-level user intent derived from execution state"""
    
    conversational_context: ConversationalContext | None = None
    """Conversational continuity across turns"""
    
    semantic_relevance: tuple[SemanticRelevance, ...] = field(default_factory=tuple)
    """Relevance scores for active domains"""
    
    entities: tuple[EntityInfo, ...] = field(default_factory=tuple)
    """Structured entities in current context"""
    
    topics: tuple[TopicInfo, ...] = field(default_factory=tuple)
    """Semantic topics/subjects in current context"""
    
    context_transition: ContextTransition = ContextTransition.NONE
    """Transition type from previous turn"""

    def __post_init__(self) -> None:
        """Validate UI context state after initialization."""
        if type(self.version) is not int:
            raise TypeError("version must be an integer")
        if self.version < 0:
            raise ValueError("version must be non-negative")
        
        if type(self.context) is not str:
            raise TypeError("context must be a string")
        if not self.context.strip():
            raise ValueError("context cannot be empty")
        
        if type(self.confidence) is not float:
            raise TypeError("confidence must be a float")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        
        if type(self.source) is not ContextSource:
            raise TypeError("source must be a ContextSource")
        
        if type(self.attention) is not AttentionLevel:
            raise TypeError("attention must be an AttentionLevel")
        
        if type(self.urgency) is not UrgencyLevel:
            raise TypeError("urgency must be an UrgencyLevel")
        
        if type(self.focus) is not FocusArea:
            raise TypeError("focus must be a FocusArea")
        
        if type(self.surfaces) is not tuple:
            raise TypeError("surfaces must be a tuple")
        for surface in self.surfaces:
            if type(surface) is not SurfaceItem:
                raise TypeError("each surface must be a SurfaceItem")
        
        if type(self.timestamp) is not datetime:
            raise TypeError("timestamp must be a datetime")
        
        if type(self.metadata) is not MappingProxyType:
            raise TypeError("metadata must be a MappingProxyType")
        
        if type(self.request_status) is not RequestStatus:
            raise TypeError("request_status must be a RequestStatus")
        
        if type(self.domains) is not tuple:
            raise TypeError("domains must be a tuple")
        for domain in self.domains:
            if type(domain) is not DomainInfo:
                raise TypeError("each domain must be a DomainInfo")
        
        if self.synthesis is not None and type(self.synthesis) is not SynthesisInfo:
            raise TypeError("synthesis must be a SynthesisInfo or None")
        
        if type(self.dependencies) is not tuple:
            raise TypeError("dependencies must be a tuple")
        for dep in self.dependencies:
            if type(dep) is not DependencyInfo:
                raise TypeError("each dependency must be a DependencyInfo")
        
        # Phase 2 validation
        if type(self.user_intent) is not UserIntent:
            raise TypeError("user_intent must be a UserIntent")
        
        if self.conversational_context is not None and type(self.conversational_context) is not ConversationalContext:
            raise TypeError("conversational_context must be a ConversationalContext or None")
        
        if type(self.semantic_relevance) is not tuple:
            raise TypeError("semantic_relevance must be a tuple")
        for rel in self.semantic_relevance:
            if type(rel) is not SemanticRelevance:
                raise TypeError("each semantic_relevance must be a SemanticRelevance")
        
        if type(self.entities) is not tuple:
            raise TypeError("entities must be a tuple")
        for entity in self.entities:
            if type(entity) is not EntityInfo:
                raise TypeError("each entity must be an EntityInfo")
        
        if type(self.topics) is not tuple:
            raise TypeError("topics must be a tuple")
        for topic in self.topics:
            if type(topic) is not TopicInfo:
                raise TypeError("each topic must be a TopicInfo")
        
        if type(self.context_transition) is not ContextTransition:
            raise TypeError("context_transition must be a ContextTransition")
        
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )