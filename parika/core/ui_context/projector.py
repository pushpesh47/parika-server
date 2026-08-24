"""
PARIKA UI Context Projector.

Derives semantic UI context from Core signals.
Subscribes to EventBus events, reads state, and maintains an immutable snapshot.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, TYPE_CHECKING

from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.context_manager.context_manager import ContextManager
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.state_manager.state_manager import StateManager
from parika.core.task_manager.task_manager import TaskManager
from parika.core.workflow_engine.workflow_engine import WorkflowEngine

from .events import UI_CONTEXT_CHANGED_EVENT, UIContextChanged
from .exceptions import UIContextNotReadyError, UIContextProjectionError
from .state import (
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

if TYPE_CHECKING:
    from parika.core.brain.brain import Brain
    from parika.core.brain.brain_response import BrainResponse
    from parika.core.planner.goal import GoalResult


@dataclass(frozen=True, slots=True, kw_only=True)
class _ContextCandidate:
    """Internal candidate for context resolution."""
    
    context: str
    confidence: float
    source: ContextSource
    focus: FocusArea
    surfaces: tuple[SurfaceItem, ...]
    metadata: MappingProxyType[str, Any]
    attention: AttentionLevel = AttentionLevel.PRIMARY
    urgency: UrgencyLevel = UrgencyLevel.NORMAL
    
    # Phase 2: Additional fields for contextual intelligence
    user_intent: UserIntent = UserIntent.UNKNOWN
    entities: tuple[EntityInfo, ...] = field(default_factory=tuple)
    topics: tuple[TopicInfo, ...] = field(default_factory=tuple)
    semantic_relevance: tuple[SemanticRelevance, ...] = field(default_factory=tuple)
    conversational_context: ConversationalContext | None = None
    context_transition: ContextTransition = ContextTransition.NONE


# Transport/orchestration capability IDs that should NOT become the primary
# semantic context when a more specific semantic capability is active.
# These are entry points, orchestration wrappers, or transport mechanisms.
_TRANSPORT_CAPABILITY_IDS: frozenset[str] = frozenset({
    "chat.respond",                    # Chat orchestration/execution wrapper
    "voice.speech_to_text",            # Voice input transport (STT orchestrator)
    "voice.text_to_speech",            # Voice output transport (TTS orchestrator)
    "voice.provider_speech_to_text",   # STT provider capability
    "voice.provider_text_to_speech",   # TTS provider capability
})


def _is_transport_capability(capability_id: str, capability_def: Any | None) -> bool:
    """Check if a capability is a transport/orchestration capability."""
    # Explicit list takes precedence
    if capability_id in _TRANSPORT_CAPABILITY_IDS:
        return True
    
    # Heuristic: provider capabilities for speech are transport
    if capability_def is not None:
        category = capability_def.category
        if category in (CapabilityCategory.SPEECH, CapabilityCategory.TEXT_TO_SPEECH):
            return True
        # Voice-tagged TOOL capabilities that are orchestrators
        if category is CapabilityCategory.TOOL:
            tags = capability_def.tags
            if "voice" in tags and "speech" in tags and "media" in tags:
                return True
    
    return False


def _is_semantic_capability(capability_id: str, capability_def: Any | None) -> bool:
    """Check if a capability is a semantic domain capability."""
    return not _is_transport_capability(capability_id, capability_def)


class UIContextProjector:
    """
    Projects semantic UI context from Core signals.
    
    Responsibilities:
    - Consume existing Core signals (TaskManager, WorkflowEngine, ContextManager, StateManager)
    - Subscribe to relevant EventBus events
    - Derive semantic context, attention, urgency, focus, and surfaces
    - Maintain current immutable snapshot with monotonically increasing version
    - Detect semantic no-op (avoid unnecessary events)
    - Publish ui.context.changed only on actual semantic changes
    - Expose current state
    - Cleanly initialize and shut down
    
    Does NOT:
    - Poll (prefers EventBus-driven updates)
    - Modify Core components
    - Contain visual rendering logic
    """
    
    # Event subscriptions - only events that can change semantic UI state
    _SUBSCRIBED_EVENTS = frozenset({
        # Task lifecycle events (high semantic significance)
        "task.started",
        "task.completed",
        "task.failed",
        "task.cancelled",
        # Workflow lifecycle events (high semantic significance)
        "workflow.started",
        "workflow.completed",
        "workflow.failed",
        "workflow.cancelled",
        # Capability execution events (semantic significance)
        "capability.execution.started",
        "capability.execution.completed",
        "capability.execution.failed",
        # Brain execution events (request-level status)
        "brain.execution.started",
        "brain.execution.completed",
        "brain.execution.failed",
        "brain.planning.started",
        "brain.planning.completed",
        "brain.planning.failed",
        "brain.execute_goal.started",
        "brain.execute_goal.completed",
        "brain.execute_goal.failed",
        # Context registry events (may indicate context changes)
        "context.registered",
        "context.updated",
        "context.removed",
    })
    
    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
        task_manager: TaskManager,
        workflow_engine: WorkflowEngine,
        context_manager: ContextManager,
        state_manager: StateManager,
        capability_registry: CapabilityRegistry,
        brain: "Brain | None" = None,
    ) -> None:
        """
        Initialize the UI Context Projector.
        
        Args:
            event_bus: EventBus for subscribing to Core events
            logger: Logger for diagnostics
            task_manager: TaskManager for reading active tasks
            workflow_engine: WorkflowEngine for reading active workflows
            context_manager: ContextManager for reading runtime contexts
            state_manager: StateManager for reading operational state
            capability_registry: CapabilityRegistry for capability metadata
            brain: Optional Brain reference to access real execution state (BrainResponse)
        """
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)
        self._task_manager = task_manager
        self._workflow_engine = workflow_engine
        self._context_manager = context_manager
        self._state_manager = state_manager
        self._capability_registry = capability_registry
        self._brain = brain
        
        self._lock = threading.RLock()
        self._current_state: UIContextState | None = None
        self._version = 0
        self._subscribed = False
        self._shutdown = False
        
        # Brain execution tracking state
        self._brain_execution_active = False
        self._brain_execution_succeeded: bool | None = None
        self._brain_request_id: str | None = None
        self._brain_goals: dict[str, dict[str, Any]] = {}  # goal_id -> goal info
        self._brain_synthesis_goal_id: str | None = None
        
        # Last active task metadata (for request status after completion)
        self._last_active_task_metadata: MappingProxyType[str, Any] | None = None
        
        # Initialize with fallback state
        self._initialize_fallback_state()
    
    def _initialize_fallback_state(self) -> None:
        """Initialize with fallback semantic state."""
        fallback_surfaces = self._build_surfaces_for_context("system")
        
        self._current_state = UIContextState(
            version=0,
            context="system",
            confidence=0.5,
            source=ContextSource.FALLBACK,
            attention=AttentionLevel.AMBIENT,
            urgency=UrgencyLevel.NORMAL,
            focus=FocusArea.GENERAL,
            surfaces=fallback_surfaces,
            timestamp=datetime.now(UTC),
            metadata=MappingProxyType({}),
            request_status=RequestStatus.FAILED,
            domains=(),
            synthesis=None,
            dependencies=(),
        )
        self._version = 0
        self._logger.info("UI Context Projector initialized with fallback state")
    
    def start(self) -> None:
        """Start the projector by subscribing to EventBus events."""
        if self._subscribed:
            return
        
        if self._shutdown:
            raise UIContextProjectionError("Cannot start after shutdown")
        
        for event_name in self._SUBSCRIBED_EVENTS:
            self._event_bus.subscribe(event_name, self._on_core_event)
        
        self._subscribed = True
        self._logger.info("UI Context Projector started, subscribed to %d events", len(self._SUBSCRIBED_EVENTS))
    
    def stop(self) -> None:
        """Stop the projector by unsubscribing from EventBus events."""
        if not self._subscribed:
            return
        
        for event_name in self._SUBSCRIBED_EVENTS:
            self._event_bus.unsubscribe(event_name, self._on_core_event)
        
        self._subscribed = False
        self._shutdown = True
        self._logger.info("UI Context Projector stopped")
    
    def set_brain(self, brain: "Brain") -> None:
        """Set the Brain reference for accessing real execution state.
        
        This is called after the Brain is constructed, since the Brain
        is created after the Projector in the runtime initialization order.
        
        Args:
            brain: The Brain instance to use for accessing real execution state.
        """
        self._brain = brain
        self._logger.debug("Brain reference set on UI Context Projector")
    
    def _on_core_event(self, payload: Any) -> None:
        """Handle Core events that may affect semantic UI state."""
        if self._shutdown:
            return
        
        # Track brain execution events for request-level status
        self._track_brain_execution(payload)
        
        try:
            self._recompute_and_publish(payload)
        except Exception:
            self._logger.exception("Error recomputing UI context from event")
    
    def _track_brain_execution(self, payload: Any) -> None:
        """Track brain execution progress events for request-level status."""
        # ProgressEvent has source_id field that identifies the event type
        source_id = getattr(payload, 'source_id', None)
        if not source_id or not source_id.startswith('brain.'):
            return
        
        stage = getattr(payload, 'stage', None)
        metadata = getattr(payload, 'metadata', {})
        
        if source_id == 'brain.execution':
            if stage and stage.value == 'started':
                self._brain_execution_active = True
                self._brain_execution_succeeded = None
                self._brain_request_id = metadata.get('request_id')
                self._brain_goals = {}
                self._brain_synthesis_goal_id = None
            elif stage and stage.value == 'completed':
                self._brain_execution_active = False
                self._brain_execution_succeeded = metadata.get('succeeded', False)
                # Use real BrainResponse for accurate state
                if self._brain is not None:
                    brain_response = self._brain.last_response
                    if brain_response is not None:
                        # Verify this response matches the request_id from the event
                        if brain_response.request_id == self._brain_request_id:
                            self._apply_brain_response(brain_response)
            elif stage and stage.value == 'failed':
                self._brain_execution_active = False
                self._brain_execution_succeeded = False
        elif source_id == 'brain.planning' and stage and stage.value == 'completed':
            # Planning completed - we could extract goal info from metadata if available
            pass
        elif source_id == 'brain.execute_goal':
            # Track individual goal execution
            goal_id = metadata.get('goal_id')
            capability_id = metadata.get('capability_id')
            if goal_id and stage:
                if goal_id not in self._brain_goals:
                    self._brain_goals[goal_id] = {'capability_id': capability_id, 'status': 'pending'}
                if stage.value == 'started':
                    self._brain_goals[goal_id]['status'] = 'running'
                elif stage.value == 'completed':
                    self._brain_goals[goal_id]['status'] = 'completed'
                elif stage.value == 'failed':
                    self._brain_goals[goal_id]['status'] = 'failed'
    
    def _apply_brain_response(self, brain_response: BrainResponse) -> None:
        """Apply real BrainResponse state to projector tracking."""
        # Extract synthesis goal ID from BrainResponse
        self._brain_synthesis_goal_id = brain_response.synthesis_goal_id
        
        # Build goal tracking from actual GoalResults
        self._brain_goals = {}
        for result in brain_response.results:
            self._brain_goals[result.goal_id] = {
                'capability_id': result.capability_id,
                'status': 'completed' if result.succeeded else ('skipped' if result.skipped else 'failed'),
                'task_id': result.task_id,
                'skipped': result.skipped,
                'failure': result.failure,
                'depends_on': result.depends_on,
            }
            # If this is the synthesis goal, mark it
            if brain_response.synthesis_goal_id == result.goal_id:
                self._brain_goals[result.goal_id]['is_synthesis'] = True
    
    def _recompute_and_publish(self, source_event: Any = None) -> None:
        """Recompute semantic state and publish if changed."""
        new_state = self._compute_semantic_state(source_event)
        
        with self._lock:
            if self._current_state is None:
                # First computation
                self._current_state = new_state
                self._version = new_state.version
                self._publish_change(new_state, 0, frozenset(new_state.__dataclass_fields__.keys()), "initialization")
                return
            
            # Check for semantic no-op
            if self._is_semantic_noop(self._current_state, new_state):
                return
            
            # Semantic change detected
            previous_version = self._current_state.version
            self._version += 1
            
            # Create new state with incremented version (including Phase 2 fields)
            changed_state = UIContextState(
                version=self._version,
                context=new_state.context,
                confidence=new_state.confidence,
                source=new_state.source,
                attention=new_state.attention,
                urgency=new_state.urgency,
                focus=new_state.focus,
                surfaces=new_state.surfaces,
                timestamp=new_state.timestamp,
                metadata=new_state.metadata,
                request_status=new_state.request_status,
                domains=new_state.domains,
                synthesis=new_state.synthesis,
                dependencies=new_state.dependencies,
                # Phase 2 fields
                user_intent=new_state.user_intent,
                conversational_context=new_state.conversational_context,
                semantic_relevance=new_state.semantic_relevance,
                entities=new_state.entities,
                topics=new_state.topics,
                context_transition=new_state.context_transition,
            )
            
            changed_fields = self._compute_changed_fields(self._current_state, changed_state)
            source_event_name = getattr(source_event, 'source_id', None) if source_event else getattr(new_state, '_source_event', None)
            
            self._current_state = changed_state
            self._publish_change(changed_state, previous_version, changed_fields, source_event_name)
    
    def _is_semantic_noop(self, old_state: UIContextState, new_state: UIContextState) -> bool:
        """Check if two states are semantically identical (no-op)."""
        return (
            old_state.context == new_state.context and
            old_state.confidence == new_state.confidence and
            old_state.source == new_state.source and
            old_state.attention == new_state.attention and
            old_state.urgency == new_state.urgency and
            old_state.focus == new_state.focus and
            self._surfaces_equal(old_state.surfaces, new_state.surfaces) and
            old_state.request_status == new_state.request_status and
            self._domains_equal(old_state.domains, new_state.domains) and
            self._synthesis_equal(old_state.synthesis, new_state.synthesis) and
            self._dependencies_equal(old_state.dependencies, new_state.dependencies)
        )
    
    def _domains_equal(self, old: tuple[DomainInfo, ...], new: tuple[DomainInfo, ...]) -> bool:
        """Check if domain tuples are semantically equal."""
        if len(old) != len(new):
            return False
        for o, n in zip(old, new):
            if (o.name != n.name or o.focus != n.focus or o.importance != n.importance or
                o.status != n.status or o.capability_ids != n.capability_ids):
                return False
        return True
    
    def _synthesis_equal(self, old: SynthesisInfo | None, new: SynthesisInfo | None) -> bool:
        """Check if synthesis info is semantically equal."""
        if old is None and new is None:
            return True
        if old is None or new is None:
            return False
        return (
            old.goal_id == new.goal_id and
            old.capability_id == new.capability_id and
            old.status == new.status and
            old.depends_on == new.depends_on and
            old.completed_dependencies == new.completed_dependencies and
            old.failed_dependencies == new.failed_dependencies
        )
    
    def _dependencies_equal(self, old: tuple[DependencyInfo, ...], new: tuple[DependencyInfo, ...]) -> bool:
        """Check if dependency tuples are semantically equal."""
        if len(old) != len(new):
            return False
        for o, n in zip(old, new):
            if (o.goal_id != n.goal_id or o.capability_id != n.capability_id or
                o.depends_on != n.depends_on or o.status != n.status or
                o.is_synthesis != n.is_synthesis):
                return False
        return True
    
    def _surfaces_equal(self, old: tuple[SurfaceItem, ...], new: tuple[SurfaceItem, ...]) -> bool:
        """Check if surface tuples are semantically equal."""
        if len(old) != len(new):
            return False
        for o, n in zip(old, new):
            if o.capability_id != n.capability_id or o.label != n.label or o.tier != n.tier or o.metadata != n.metadata:
                return False
        return True
    
    def _compute_changed_fields(self, old: UIContextState, new: UIContextState) -> frozenset[str]:
        """Compute which fields changed semantically."""
        fields = set()
        if old.context != new.context:
            fields.add("context")
        if old.confidence != new.confidence:
            fields.add("confidence")
        if old.source != new.source:
            fields.add("source")
        if old.attention != new.attention:
            fields.add("attention")
        if old.urgency != new.urgency:
            fields.add("urgency")
        if old.focus != new.focus:
            fields.add("focus")
        if not self._surfaces_equal(old.surfaces, new.surfaces):
            fields.add("surfaces")
        if old.metadata != new.metadata:
            fields.add("metadata")
        if old.request_status != new.request_status:
            fields.add("request_status")
        if not self._domains_equal(old.domains, new.domains):
            fields.add("domains")
        if not self._synthesis_equal(old.synthesis, new.synthesis):
            fields.add("synthesis")
        if not self._dependencies_equal(old.dependencies, new.dependencies):
            fields.add("dependencies")
        return frozenset(fields)
    
    def _publish_change(
        self,
        new_state: UIContextState,
        previous_version: int,
        changed_fields: frozenset[str],
        source_event: str | None,
    ) -> None:
        """Publish UI context changed event."""
        event = UIContextChanged(
            version=new_state.version,
            previous_version=previous_version,
            changed_fields=changed_fields,
            source_event=source_event,
        )
        
        self._event_bus.publish(UI_CONTEXT_CHANGED_EVENT, event)
        self._logger.debug(
            "UI context changed: v%d -> v%d, fields=%s",
            previous_version,
            new_state.version,
            sorted(changed_fields),
        )
    
    def _compute_semantic_state(self, source_event: Any = None) -> UIContextState:
        """
        Compute the current semantic UI state from Core signals.
        
        Resolution priority (highest to lowest):
        1. Explicit active capability/task (strongest evidence)
        2. Active workflow execution
        3. Runtime ContextManager context
        4. Interaction state
        5. Fallback
        """
        # Try to resolve from active task (highest priority)
        task_candidate = self._resolve_from_active_task()
        if task_candidate is not None:
            return self._build_state_from_candidate(task_candidate, source_event)
        
        # Try to resolve from active workflow
        workflow_candidate = self._resolve_from_active_workflow()
        if workflow_candidate is not None:
            return self._build_state_from_candidate(workflow_candidate, source_event)
        
        # Try to resolve from ContextManager
        context_candidate = self._resolve_from_context_manager()
        if context_candidate is not None:
            return self._build_state_from_candidate(context_candidate, source_event)
        
        # Try to resolve from interaction state
        interaction_candidate = self._resolve_from_interaction_state()
        if interaction_candidate is not None:
            return self._build_state_from_candidate(interaction_candidate, source_event)
        
        # Special case: brain execution completed with real BrainResponse
        # Use authoritative BrainResponse for final state
        if self._brain is not None:
            brain_response = self._brain.last_response
            if brain_response is not None:
                return self._build_state_from_brain_response(brain_response, source_event)
        
        # Special case: no active tasks but we have recent task metadata
        # Preserve the last known semantic context as ambient instead of falling back
        if (self._last_active_task_metadata is not None and 
            self._current_state is not None and
            self._current_state.context != "system"):
            # Build a state based on last known context
            return self._build_state_from_last_metadata()
        
        # Special case: brain execution just completed but no active tasks
        # Use last known active task metadata to preserve context
        if (self._brain_execution_succeeded is not None and 
            self._last_active_task_metadata is not None and
            self._current_state is not None):
            # Build a state based on last known context
            return self._build_state_from_last_metadata()
        
        
        # Fallback
        return self._build_fallback_state()

    # Task resolution

    def _resolve_from_active_task(self) -> _ContextCandidate | None:
        """Resolve semantic context from active tasks."""
        tasks = self._task_manager.get_all()
        
        # Active task statuses
        active_statuses = {"RUNNING", "PENDING", "PAUSED", "WAITING"}
        
        active_tasks = [
            task for task in tasks.values()
            if task.status.name in active_statuses
        ]
        
        # Also consider recently completed semantic tasks whose parent is still active
        # This prevents semantic context from falling back when child completes but parent continues
        active_task_ids = {task.id for task in active_tasks}
        completed_semantic_tasks = [
            task for task in tasks.values()
            if task.status.name == "COMPLETED"
            and task.parent_task_id in active_task_ids
        ]
        
        all_candidate_tasks = active_tasks + completed_semantic_tasks
        
        if not all_candidate_tasks:
            return None
        
        # Build task info tuples for all tasks (for metadata)
        all_task_infos = []
        for task in all_candidate_tasks:
            capability_id = task.request.capability_id
            capability_def = self._capability_registry.get(capability_id) if self._capability_registry.contains(capability_id) else None
            all_task_infos.append((task, capability_id, capability_def))
        
        # Classify tasks by capability type
        semantic_tasks = []
        transport_tasks = []
        
        for task_info in all_task_infos:
            task, capability_id, capability_def = task_info
            if _is_semantic_capability(capability_id, capability_def):
                semantic_tasks.append(task_info)
            else:
                transport_tasks.append(task_info)
        
        # Prefer semantic tasks over transport tasks
        candidate_tasks = semantic_tasks if semantic_tasks else transport_tasks
        
        if not candidate_tasks:
            return None
        
        # Build task hierarchy: find leaf tasks (tasks that are not parents of other candidate tasks)
        candidate_task_ids = {task.id for task, _, _ in candidate_tasks}
        child_parent_ids = {task.parent_task_id for task, _, _ in candidate_tasks if task.parent_task_id}
        leaf_tasks = [(task, cap_id, cap_def) for task, cap_id, cap_def in candidate_tasks if task.id not in child_parent_ids]
        
        # Prefer leaf tasks (most specific capabilities), fall back to all candidates
        selection_pool = leaf_tasks if leaf_tasks else candidate_tasks
        
        # Deterministic selection: 
        # 1. Active (RUNNING/PENDING/PAUSED/WAITING) > COMPLETED
        # 2. RUNNING > PENDING > PAUSED > WAITING > COMPLETED
        # 3. Semantic specificity (more specific context first)
        # 4. Recency (started_at/created_at)
        def task_priority(item):
            task, capability_id, capability_def = item
            status_order = {"RUNNING": 0, "PENDING": 1, "PAUSED": 2, "WAITING": 3, "COMPLETED": 4}
            status_rank = status_order.get(task.status.name, 5)
            
            # Semantic specificity: prefer capabilities that map to specific domains
            # (not generic "chat", "voice", "system")
            context, _, _ = self._infer_context_from_capability(capability_id, capability_def)
            specificity_rank = 0 if context not in ("chat", "voice", "system") else 1
            
            time_key = task.started_at or task.created_at
            return (status_rank, specificity_rank, time_key)
        
        primary_task, capability_id, capability_def = min(selection_pool, key=task_priority)
        
        # Determine semantic context from capability
        context, focus, confidence = self._infer_context_from_capability(capability_id, capability_def)
        
        # Build surfaces from related capabilities (enhanced with active capabilities)
        active_capability_ids = {
            task.request.capability_id
            for task, _, _ in candidate_tasks
            if _is_semantic_capability(task.request.capability_id, 
                self._capability_registry.get(task.request.capability_id) if self._capability_registry.contains(task.request.capability_id) else None)
        }
        surfaces = self._build_surfaces_for_context(context, active_capability_ids)
        
        # Determine attention from task status
        attention = self._attention_from_task_status(primary_task.status.name)
        
        # Determine urgency - check for critical system events
        urgency = self._determine_urgency()
        
        # Build enriched metadata with multi-agent information (include all tasks for complete picture)
        metadata = self._build_enriched_metadata(primary_task, capability_id, all_task_infos)
        
        # Store for request status after task completion
        self._last_active_task_metadata = metadata
        
        return _ContextCandidate(
            context=context,
            confidence=confidence,
            source=ContextSource.TASK,
            focus=focus,
            surfaces=surfaces,
            metadata=metadata,
            attention=attention,
            urgency=urgency,
            # Phase 2: These will be computed in _build_state_from_candidate
            # but we can pre-compute some if needed
        )
    
    def _resolve_from_active_workflow(self) -> _ContextCandidate | None:
        """Resolve semantic context from active workflow executions."""
        # WorkflowEngine doesn't expose a simple "get active executions" method
        # We would need to track workflow.started/completed events
        # For now, return None - workflow context is inferred from tasks
        return None
    
    def _resolve_from_context_manager(self) -> _ContextCandidate | None:
        """Resolve semantic context from ContextManager registry."""
        contexts = self._context_manager.get_all()
        
        if not contexts:
            return None
        
        # Prefer TASK or INTERACTION type contexts
        preferred_types = {"task", "interaction", "workflow", "module"}
        preferred = [c for c in contexts if c.context_type.value in preferred_types]
        candidates = preferred if preferred else list(contexts)
        
        if not candidates:
            return None
        
        # Deterministic: most recently updated
        latest = max(candidates, key=lambda c: c.updated_at)
        
        context_name = self._context_type_to_semantic(latest.context_type.value)
        surfaces = self._build_surfaces_for_context(context_name)
        
        metadata = MappingProxyType({
            "context_id": latest.context_id,
            "context_type": latest.context_type.value,
        })
        
        return _ContextCandidate(
            context=context_name,
            confidence=0.6,
            source=ContextSource.SYSTEM,
            focus=FocusArea.GENERAL,
            surfaces=surfaces,
            metadata=metadata,
            attention=AttentionLevel.SECONDARY,
            urgency=self._determine_urgency(),
        )
    
    def _resolve_from_interaction_state(self) -> _ContextCandidate | None:
        """Resolve semantic context from StateManager interaction state."""
        interaction_state = self._state_manager.get_interaction_state()
        
        # Map interaction states to semantic contexts
        if interaction_state.name == "LISTENING":
            return _ContextCandidate(
                context="voice",
                confidence=0.7,
                source=ContextSource.INTERACTION,
                focus=FocusArea.VOICE_INPUT,
                surfaces=self._build_surfaces_for_context("voice"),
                metadata=MappingProxyType({"interaction_state": "listening"}),
                attention=AttentionLevel.PRIMARY,
                urgency=self._determine_urgency(),
            )
        elif interaction_state.name == "THINKING":
            return _ContextCandidate(
                context="system",
                confidence=0.5,
                source=ContextSource.INTERACTION,
                focus=FocusArea.GENERAL,
                surfaces=self._build_surfaces_for_context("system"),
                metadata=MappingProxyType({"interaction_state": "thinking"}),
                attention=AttentionLevel.SECONDARY,
                urgency=self._determine_urgency(),
            )
        elif interaction_state.name == "RESPONDING":
            return _ContextCandidate(
                context="chat",
                confidence=0.6,
                source=ContextSource.INTERACTION,
                focus=FocusArea.GENERAL,
                surfaces=self._build_surfaces_for_context("chat"),
                metadata=MappingProxyType({"interaction_state": "responding"}),
                attention=AttentionLevel.PRIMARY,
                urgency=self._determine_urgency(),
            )
        
        return None
    
    def _build_fallback_state(self) -> UIContextState:
        """Build fallback semantic state."""
        candidate = _ContextCandidate(
            context="system",
            confidence=0.3,
            source=ContextSource.FALLBACK,
            focus=FocusArea.GENERAL,
            surfaces=self._build_surfaces_for_context("system"),
            metadata=MappingProxyType({}),
        )
        
        # Phase 2: Minimal contextual intelligence for fallback
        user_intent = UserIntent.UNKNOWN
        entities = ()
        topics = ()
        semantic_relevance = ()
        freshness_infos = ()
        
        # Empty domains for fallback
        domains = ()
        synthesis = None
        dependencies = ()
        
        # Conversational context
        conversational_context = self._compute_conversational_context(candidate, self._current_state)
        context_transition = conversational_context.contextual_transition
        
        return UIContextState(
            version=self._version + 1,
            context="system",
            confidence=0.3,
            source=ContextSource.FALLBACK,
            attention=AttentionLevel.AMBIENT,
            urgency=self._determine_urgency(),
            focus=FocusArea.GENERAL,
            surfaces=candidate.surfaces,
            timestamp=datetime.now(UTC),
            metadata=MappingProxyType({}),
            request_status=RequestStatus.FAILED,
            domains=domains,
            synthesis=synthesis,
            dependencies=dependencies,
            # Phase 2 fields
            user_intent=user_intent,
            conversational_context=conversational_context,
            semantic_relevance=semantic_relevance,
            entities=entities,
            topics=topics,
            context_transition=context_transition,
        )
    
    def _build_state_from_brain_response(self, brain_response: BrainResponse, source_event: Any = None) -> UIContextState:
        """Build UIContextState from authoritative BrainResponse.
        
        This is used when a request completes and we have the authoritative
        BrainResponse with all goal results, synthesis info, and status.
        """
        # Convert BrainResponse RequestStatus to UIContextState RequestStatus
        brain_status = brain_response.status
        if brain_status.value == "success":
            request_status = RequestStatus.SUCCESS
        elif brain_status.value == "partial_success":
            request_status = RequestStatus.PARTIAL_SUCCESS
        else:
            request_status = RequestStatus.FAILED
        
        domains = self._compute_domains_from_brain_response(brain_response)
        synthesis = self._compute_synthesis_from_brain_response(brain_response)
        dependencies = self._compute_dependencies_from_brain_response(brain_response)
        
        # Determine primary context from the goals
        if brain_response.results:
            # Use the first non-synthesis goal for primary context, or synthesis if all are synthesis
            primary_goal = None
            for result in brain_response.results:
                if result.goal_id != brain_response.synthesis_goal_id:
                    primary_goal = result
                    break
            if primary_goal is None:
                primary_goal = brain_response.results[0]
            
            context, focus, confidence = self._infer_context_from_capability(primary_goal.capability_id, None)
        else:
            context = "system"
            focus = FocusArea.GENERAL
            confidence = 0.3
        
        # Build surfaces from all goal capability IDs
        all_capability_ids = {result.capability_id for result in brain_response.results}
        
        # Build goal results dict by capability_id for surface metadata enrichment
        brain_goal_results = {result.goal_id: result for result in brain_response.results}
        
        surfaces = self._build_surfaces_for_context(context, all_capability_ids, brain_goal_results, brain_response.synthesis_goal_id)
        
        # Build metadata from BrainResponse
        metadata = self._build_metadata_from_brain_response(brain_response)
        
        # ========== Phase 2: Compute contextual intelligence ==========
        user_intent = self._compute_user_intent(
            _ContextCandidate(
                context=context,
                confidence=confidence,
                source=ContextSource.TASK,
                focus=focus,
                surfaces=surfaces,
                metadata=metadata,
            ),
            brain_response,
        )
        
        entities = self._compute_entities(
            _ContextCandidate(
                context=context,
                confidence=confidence,
                source=ContextSource.TASK,
                focus=focus,
                surfaces=surfaces,
                metadata=metadata,
            ),
            brain_response,
        )
        
        topics = self._compute_topics(
            _ContextCandidate(
                context=context,
                confidence=confidence,
                source=ContextSource.TASK,
                focus=focus,
                surfaces=surfaces,
                metadata=metadata,
            ),
            brain_response,
        )
        
        semantic_relevance = self._compute_semantic_relevance(
            _ContextCandidate(
                context=context,
                confidence=confidence,
                source=ContextSource.TASK,
                focus=focus,
                surfaces=surfaces,
                metadata=metadata,
            ),
            brain_response,
        )
        
        freshness_infos = self._compute_freshness(
            _ContextCandidate(
                context=context,
                confidence=confidence,
                source=ContextSource.TASK,
                focus=focus,
                surfaces=surfaces,
                metadata=metadata,
            ),
            brain_response,
        )
        
        # Enhance domains with Phase 2 info
        domains = self._enhance_domains_with_phase2(
            domains, 
            _ContextCandidate(context=context, confidence=confidence, source=ContextSource.TASK, focus=focus, surfaces=surfaces, metadata=metadata),
            entities, topics, freshness_infos, semantic_relevance
        )
        
        # Enhance surfaces with Phase 2 info
        surfaces = self._enhance_surfaces_with_phase2(
            surfaces,
            _ContextCandidate(context=context, confidence=confidence, source=ContextSource.TASK, focus=focus, surfaces=surfaces, metadata=metadata),
            freshness_infos, semantic_relevance, brain_response
        )
        
        # Enhance synthesis with Phase 2 info
        synthesis = self._enhance_synthesis_with_phase2(synthesis, _ContextCandidate(context=context, confidence=confidence, source=ContextSource.TASK, focus=focus, surfaces=surfaces, metadata=metadata))
        
        # Enhance dependencies with Phase 2 info
        dependencies = self._enhance_dependencies_with_phase2(dependencies, _ContextCandidate(context=context, confidence=confidence, source=ContextSource.TASK, focus=focus, surfaces=surfaces, metadata=metadata))
        
        # Conversational context
        conversational_context = self._compute_conversational_context(
            _ContextCandidate(context=context, confidence=confidence, source=ContextSource.TASK, focus=focus, surfaces=surfaces, metadata=metadata),
            self._current_state,
        )
        
        # Context transition
        context_transition = conversational_context.contextual_transition
        
        return UIContextState(
            version=self._version + 1,
            context=context,
            confidence=confidence,
            source=ContextSource.TASK,
            attention=AttentionLevel.AMBIENT,  # Request completed
            urgency=self._determine_urgency(),
            focus=focus,
            surfaces=surfaces,
            timestamp=datetime.now(UTC),
            metadata=metadata,
            request_status=request_status,
            domains=domains,
            synthesis=synthesis,
            dependencies=dependencies,
            # Phase 2 fields
            user_intent=user_intent,
            conversational_context=conversational_context,
            semantic_relevance=semantic_relevance,
            entities=entities,
            topics=topics,
            context_transition=context_transition,
        )
    
    def _compute_domains_from_brain_response(self, brain_response: BrainResponse) -> tuple[DomainInfo, ...]:
        """Compute domains from BrainResponse goal results."""
        if not brain_response.results:
            return ()
        
        # Group goals by domain
        domain_goals: dict[str, list[GoalResult]] = {}
        for result in brain_response.results:
            domain_name, _, _ = self._infer_context_from_capability(result.capability_id, None)
            if domain_name not in domain_goals:
                domain_goals[domain_name] = []
            domain_goals[domain_name].append(result)
        
        domains = []
        total_goals = len(brain_response.results)
        
        for domain_name, goals in domain_goals.items():
            focus_str = "general"
            try:
                focus = FocusArea(focus_str)
            except ValueError:
                focus = FocusArea.GENERAL
            
            importance = len(goals) / total_goals if total_goals > 0 else 0.5
            
            # Determine domain status from actual goal states
            failed_count = sum(1 for g in goals if not g.succeeded and not g.skipped)
            completed_count = sum(1 for g in goals if g.succeeded)
            skipped_count = sum(1 for g in goals if g.skipped)
            
            if failed_count > 0 and completed_count > 0:
                status = "partial"
            elif completed_count == len(goals):
                status = "completed"
            elif failed_count > 0 and completed_count == 0:
                status = "failed"
            elif skipped_count > 0:
                status = "skipped"
            else:
                status = "completed"
            
            # Get capability IDs for this domain
            domain_caps = tuple(g.capability_id for g in goals)
            
            # Determine domain category from the first goal's capability
            first_goal = goals[0] if goals else None
            domain_category = None
            primary_entities = ()
            primary_topics = ()
            
            if first_goal:
                cap_def = self._capability_registry.get(first_goal.capability_id) if self._capability_registry.contains(first_goal.capability_id) else None
                if cap_def:
                    domain_category = cap_def.category.value
            
            domains.append(DomainInfo(
                name=domain_name,
                focus=focus,
                importance=importance,
                status=status,
                capability_ids=domain_caps,
                domain_category=domain_category,
                primary_entities=primary_entities,
                primary_topics=primary_topics,
            ))
        
        # Sort by importance descending
        domains.sort(key=lambda d: d.importance, reverse=True)
        return tuple(domains)
    
    def _compute_synthesis_from_brain_response(self, brain_response: BrainResponse) -> SynthesisInfo | None:
        """Compute synthesis info from BrainResponse."""
        if brain_response.synthesis_goal_id is None:
            return None
        
        # Find the synthesis goal result
        synthesis_result = None
        for result in brain_response.results:
            if result.goal_id == brain_response.synthesis_goal_id:
                synthesis_result = result
                break
        
        if synthesis_result is None:
            return None
        
        # Get dependencies from the synthesis goal's actual depends_on
        depends_on = synthesis_result.depends_on
        
        # Build completed/failed dependencies from actual goal results
        completed_deps = ()
        failed_deps = ()
        for result in brain_response.results:
            if result.goal_id in depends_on:
                if result.succeeded:
                    completed_deps += (result.goal_id,)
                else:
                    failed_deps += (result.goal_id,)
        
        # Determine synthesis status
        if synthesis_result.succeeded:
            synth_status = "completed"
        elif synthesis_result.skipped:
            synth_status = "skipped"
        else:
            synth_status = "failed"
        
        # Determine synthesis domain and semantic type
        synthesis_domain, synthesis_semantic_type, _, _ = self._get_semantic_info_from_capability(synthesis_result.capability_id)
        
        # Get dependency domains
        dependency_domains = ()
        for result in brain_response.results:
            if result.goal_id in depends_on:
                dep_domain, _, _, _ = self._get_semantic_info_from_capability(result.capability_id)
                if dep_domain:
                    dependency_domains += (dep_domain,)
        
        return SynthesisInfo(
            goal_id=brain_response.synthesis_goal_id,
            capability_id=synthesis_result.capability_id,
            status=synth_status,
            depends_on=depends_on,
            completed_dependencies=completed_deps,
            failed_dependencies=failed_deps,
            domain=synthesis_domain,
            semantic_type=synthesis_semantic_type,
            dependency_domains=dependency_domains,
        )
    
    def _compute_dependencies_from_brain_response(self, brain_response: BrainResponse) -> tuple[DependencyInfo, ...]:
        """Compute dependencies from BrainResponse goal results."""
        deps = []
        for result in brain_response.results:
            # Determine status from GoalResult
            if result.skipped:
                status = "skipped"
            elif result.succeeded:
                status = "completed"
            else:
                status = "failed"
            
            # Determine if this is the synthesis goal
            is_synthesis = (brain_response.synthesis_goal_id == result.goal_id)
            
            # Use actual depends_on from GoalResult
            depends_on = result.depends_on
            
            # Use actual capability_id from GoalResult
            capability_id = result.capability_id
            
            # Get semantic info from capability registry
            domain, semantic_type, category, tags = self._get_semantic_info_from_capability(capability_id)
            
            # Get dependency domains
            dependency_domains = ()
            for dep_id in depends_on:
                # Find the goal result for this dependency
                for r in brain_response.results:
                    if r.goal_id == dep_id:
                        dep_domain, _, _, _ = self._get_semantic_info_from_capability(r.capability_id)
                        if dep_domain:
                            dependency_domains += (dep_domain,)
                        break
            
            deps.append(DependencyInfo(
                goal_id=result.goal_id,
                capability_id=capability_id,
                depends_on=depends_on,
                status=status,
                is_synthesis=is_synthesis,
                domain=domain,
                semantic_type=semantic_type,
                capability_category=category,
                capability_tags=tags,
                dependency_domains=dependency_domains,
            ))
        return tuple(deps)
    
    def _build_metadata_from_brain_response(self, brain_response: BrainResponse) -> MappingProxyType[str, Any]:
        """Build metadata from BrainResponse."""
        active_agents_list = []
        active_domains_list = []
        active_semantic_capabilities = []
        active_all_capabilities = []
        task_counts = {
            "running": 0,
            "waiting": 0,
            "completed": 0,
            "pending": 0,
            "failed": 0,
            "total": len(brain_response.results),
        }
        
        # Update task counts from goal results
        for result in brain_response.results:
            if result.succeeded:
                task_counts["completed"] += 1
            elif result.skipped:
                task_counts["pending"] += 1  # Skipped counted as pending
            else:
                task_counts["failed"] += 1
        
        # Build active capabilities
        for result in brain_response.results:
            cap_id = result.capability_id
            active_all_capabilities.append(cap_id)
            # Check if semantic
            if not _is_transport_capability(cap_id, None):
                active_semantic_capabilities.append(cap_id)
        
        # Build domains
        domain_map = {}
        for result in brain_response.results:
            domain_name, domain_focus, _ = self._infer_context_from_capability(result.capability_id, None)
            if domain_name not in domain_map:
                domain_map[domain_name] = {"context": domain_name, "focus": domain_focus.value, "task_count": 0}
            domain_map[domain_name]["task_count"] += 1
        
        for domain_info in domain_map.values():
            active_domains_list.append(domain_info)
        
        metadata_dict = {
            "task": {
                "id": brain_response.request_id,
                "capability_id": brain_response.synthesis_goal_id or "unknown",
                "status": "COMPLETED",
            },
            "agent": {},
            "activity": {
                "active_agents": active_agents_list,
                "active_domains": active_domains_list,
                "active_semantic_capabilities": sorted(active_semantic_capabilities),
                "active_capabilities": sorted(active_all_capabilities),
                "task_counts": task_counts,
            },
        }
        
        return MappingProxyType(metadata_dict)
    
    def _build_state_from_last_metadata(self) -> UIContextState:
        """Build UIContextState from last known active task metadata."""
        metadata = self._last_active_task_metadata
        # Use current state's context/focus as base, but with updated request_status
        current = self._current_state
        
        request_status = self._compute_request_status(metadata)
        domains = self._compute_domains(metadata)
        synthesis = self._compute_synthesis(metadata)
        dependencies = self._compute_dependencies(metadata)
        
        # Rebuild surfaces from active capabilities in metadata
        active_capabilities = metadata.get("activity", {}).get("active_capabilities", [])
        surfaces = self._build_surfaces_for_context(current.context, set(active_capabilities))
        
        # ========== Phase 2: Compute contextual intelligence ==========
        # For last metadata state, we don't have brain response
        brain_response = None
        
        candidate = _ContextCandidate(
            context=current.context,
            confidence=current.confidence,
            source=current.source,
            focus=current.focus,
            surfaces=surfaces,
            metadata=metadata,
        )
        
        user_intent = self._compute_user_intent(candidate, brain_response)
        entities = self._compute_entities(candidate, brain_response)
        topics = self._compute_topics(candidate, brain_response)
        semantic_relevance = self._compute_semantic_relevance(candidate, brain_response)
        freshness_infos = self._compute_freshness(candidate, brain_response)
        
        # Enhance domains with Phase 2 info
        domains = self._enhance_domains_with_phase2(domains, candidate, entities, topics, freshness_infos, semantic_relevance)
        
        # Enhance surfaces with Phase 2 info
        surfaces = self._enhance_surfaces_with_phase2(surfaces, candidate, freshness_infos, semantic_relevance, brain_response)
        
        # Enhance synthesis with Phase 2 info
        synthesis = self._enhance_synthesis_with_phase2(synthesis, candidate)
        
        # Enhance dependencies with Phase 2 info
        dependencies = self._enhance_dependencies_with_phase2(dependencies, candidate)
        
        # Conversational context
        conversational_context = self._compute_conversational_context(candidate, self._current_state)
        
        # Context transition
        context_transition = conversational_context.contextual_transition
        
        return UIContextState(
            version=self._version + 1,
            context=current.context,
            confidence=current.confidence,
            source=current.source,
            attention=AttentionLevel.AMBIENT,  # No active tasks
            urgency=self._determine_urgency(),
            focus=current.focus,
            surfaces=surfaces,
            timestamp=datetime.now(UTC),
            metadata=metadata,
            request_status=request_status,
            domains=domains,
            synthesis=synthesis,
            dependencies=dependencies,
            # Phase 2 fields
            user_intent=user_intent,
            conversational_context=conversational_context,
            semantic_relevance=semantic_relevance,
            entities=entities,
            topics=topics,
            context_transition=context_transition,
        )
    
    def _build_state_from_candidate(self, candidate: _ContextCandidate, source_event: Any = None) -> UIContextState:
        """Build UIContextState from a resolved candidate."""
        # Compute Phase 1 fields from candidate metadata and brain execution state
        request_status = self._compute_request_status(candidate.metadata)
        domains = self._compute_domains(candidate.metadata)
        synthesis = self._compute_synthesis(candidate.metadata)
        dependencies = self._compute_dependencies(candidate.metadata)
        
        # ========== Phase 2: Compute contextual intelligence ==========
        # Try to get brain response for enhanced computation
        brain_response = None
        if self._brain is not None:
            brain_response = self._brain.last_response
        
        # If candidate already has Phase 2 fields, use them
        if candidate.user_intent != UserIntent.UNKNOWN:
            user_intent = candidate.user_intent
        else:
            user_intent = self._compute_user_intent(candidate, brain_response)
        
        if candidate.entities:
            entities = candidate.entities
        else:
            entities = self._compute_entities(candidate, brain_response)
        
        if candidate.topics:
            topics = candidate.topics
        else:
            topics = self._compute_topics(candidate, brain_response)
        
        if candidate.semantic_relevance:
            semantic_relevance = candidate.semantic_relevance
        else:
            semantic_relevance = self._compute_semantic_relevance(candidate, brain_response)
        
        freshness_infos = self._compute_freshness(candidate, brain_response)
        
        # Enhance domains with Phase 2 info
        domains = self._enhance_domains_with_phase2(domains, candidate, entities, topics, freshness_infos, semantic_relevance)
        
        # Enhance surfaces with Phase 2 info
        surfaces = self._enhance_surfaces_with_phase2(candidate.surfaces, candidate, freshness_infos, semantic_relevance, brain_response)
        
        # Enhance synthesis with Phase 2 info
        synthesis = self._enhance_synthesis_with_phase2(synthesis, candidate)
        
        # Enhance dependencies with Phase 2 info
        dependencies = self._enhance_dependencies_with_phase2(dependencies, candidate)
        
        # Conversational context
        conversational_context = self._compute_conversational_context(candidate, self._current_state, source_event)
        
        # Context transition
        context_transition = conversational_context.contextual_transition
        
        return UIContextState(
            version=self._version + 1,
            context=candidate.context,
            confidence=candidate.confidence,
            source=candidate.source,
            attention=candidate.attention,
            urgency=candidate.urgency,
            focus=candidate.focus,
            surfaces=surfaces,
            timestamp=datetime.now(UTC),
            metadata=candidate.metadata,
            request_status=request_status,
            domains=domains,
            synthesis=synthesis,
            dependencies=dependencies,
            # Phase 2 fields
            user_intent=user_intent,
            conversational_context=conversational_context,
            semantic_relevance=semantic_relevance,
            entities=entities,
            topics=topics,
            context_transition=context_transition,
        )
    

    def _build_enriched_metadata(
        self,
        primary_task: Any,
        primary_capability_id: str,
        candidate_tasks: list[tuple[Any, str, Any]],
    ) -> MappingProxyType[str, Any]:
        """Build enriched metadata with multi-agent runtime information."""
        # Extract primary task info
        primary_task_metadata = primary_task.request.metadata
        primary_agent_id = primary_task_metadata.get("agent_id")
        primary_agent_specialization = primary_task_metadata.get("agent_specialization")
        primary_agent_confidence = primary_task_metadata.get("agent_confidence")
        
        # Collect active agents from all candidate tasks
        active_agents: dict[str, dict[str, Any]] = {}
        active_domains: dict[str, dict[str, Any]] = {}
        active_semantic_capabilities: set[str] = set()
        active_all_capabilities: set[str] = set()
        
        running_count = 0
        waiting_count = 0
        completed_count = 0
        pending_count = 0
        
        for task, cap_id, cap_def in candidate_tasks:
            task_metadata = task.request.metadata
            agent_id = task_metadata.get("agent_id")
            agent_specialization = task_metadata.get("agent_specialization")
            agent_confidence = task_metadata.get("agent_confidence")
            
            # Count task statuses
            status = task.status.name
            if status == "RUNNING":
                running_count += 1
            elif status == "WAITING":
                waiting_count += 1
            elif status == "COMPLETED":
                completed_count += 1
            elif status == "PENDING":
                pending_count += 1
            
            # Track active semantic capabilities
            if _is_semantic_capability(cap_id, cap_def):
                active_semantic_capabilities.add(cap_id)
            
            # Track all active capabilities (including transport)
            active_all_capabilities.add(cap_id)
            
            # Track active agents
            if agent_id:
                if agent_id not in active_agents:
                    active_agents[agent_id] = {
                        "id": agent_id,
                        "specialization": agent_specialization or "unknown",
                        "confidence": agent_confidence,
                        "task_count": 0,
                        "domains": set(),
                    }
                active_agents[agent_id]["task_count"] += 1
                # Infer domain from capability
                domain, _, _ = self._infer_context_from_capability(cap_id, cap_def)
                active_agents[agent_id]["domains"].add(domain)
            
            # Track active domains
            domain, domain_focus, _ = self._infer_context_from_capability(cap_id, cap_def)
            if domain not in active_domains:
                active_domains[domain] = {
                    "context": domain,
                    "focus": domain_focus.value,
                    "task_count": 0,
                }
            active_domains[domain]["task_count"] += 1
        
        # Build active agents list (sorted for determinism)
        active_agents_list = []
        for agent_id in sorted(active_agents.keys()):
            agent_info = active_agents[agent_id]
            active_agents_list.append({
                "id": agent_info["id"],
                "specialization": agent_info["specialization"],
                "confidence": agent_info["confidence"],
                "task_count": agent_info["task_count"],
                "domains": sorted(agent_info["domains"]),
            })
        
        # Build active domains list (sorted for determinism)
        active_domains_list = []
        for domain in sorted(active_domains.keys()):
            domain_info = active_domains[domain]
            active_domains_list.append({
                "context": domain_info["context"],
                "focus": domain_info["focus"],
                "task_count": domain_info["task_count"],
            })
        
        metadata_dict = {
            "task": {
                "id": primary_task.id,
                "capability_id": primary_capability_id,
                "status": primary_task.status.name,
            },
            "agent": {
                "id": primary_agent_id,
                "specialization": primary_agent_specialization,
                "confidence": primary_agent_confidence,
            } if primary_agent_id else {},
            "activity": {
                "active_agents": active_agents_list,
                "active_domains": active_domains_list,
                "active_semantic_capabilities": sorted(active_semantic_capabilities),
                "active_capabilities": sorted(active_all_capabilities),
                "task_counts": {
                    "running": running_count,
                    "waiting": waiting_count,
                    "completed": completed_count,
                    "pending": pending_count,
                    "total": running_count + waiting_count + completed_count + pending_count,
                },
            },
        }
        
        return MappingProxyType(metadata_dict)
    
    def _compute_request_status(self, metadata: MappingProxyType[str, Any]) -> RequestStatus:
        """Compute request-level status from metadata and brain execution state."""
        # If we have a real BrainResponse, use its authoritative status
        if self._brain is not None:
            brain_response = self._brain.last_response
            if brain_response is not None:
                # Convert BrainResponse.RequestStatus to UIContextState.RequestStatus
                brain_status = brain_response.status
                if brain_status.value == "success":
                    return RequestStatus.SUCCESS
                elif brain_status.value == "partial_success":
                    return RequestStatus.PARTIAL_SUCCESS
                else:
                    return RequestStatus.FAILED
        
        # If we have brain execution tracking, use it
        if self._brain_execution_succeeded is not None:
            # For brain execution completion, get current task counts directly
            # since stored metadata may be stale (captured when tasks were RUNNING)
            tasks = self._task_manager.get_all()
            failed_count = sum(1 for t in tasks.values() if t.status.name == "FAILED")
            completed_count = sum(1 for t in tasks.values() if t.status.name == "COMPLETED")
            running_count = sum(1 for t in tasks.values() if t.status.name == "RUNNING")
            
            # If brain execution completed and we have failed tasks but synthesis succeeded
            if self._brain_execution_succeeded:
                # Check if any non-synthesis goals failed
                if failed_count > 0:
                    return RequestStatus.PARTIAL_SUCCESS
                return RequestStatus.SUCCESS
            else:
                return RequestStatus.FAILED
        
        # Fallback: infer from task counts in metadata
        activity = metadata.get("activity", {})
        task_counts = activity.get("task_counts", {})
        failed_count = task_counts.get("failed", 0)
        completed_count = task_counts.get("completed", 0)
        running_count = task_counts.get("running", 0)
        
        if failed_count > 0 and completed_count > 0:
            return RequestStatus.PARTIAL_SUCCESS
        elif completed_count > 0 and failed_count == 0 and running_count == 0:
            return RequestStatus.SUCCESS
        else:
            return RequestStatus.FAILED
    
    def _compute_domains(self, metadata: MappingProxyType[str, Any]) -> tuple[DomainInfo, ...]:
        """Compute multiple semantic domains from metadata."""
        # If we have a real BrainResponse, use its authoritative goal results for domain status
        if self._brain is not None:
            brain_response = self._brain.last_response
            if brain_response is not None:
                # Group goals by domain
                domain_goals: dict[str, list[GoalResult]] = {}
                for result in brain_response.results:
                    domain_name, _, _ = self._infer_context_from_capability(result.capability_id, None)
                    if domain_name not in domain_goals:
                        domain_goals[domain_name] = []
                    domain_goals[domain_name].append(result)
                
                domains = []
                total_goals = len(brain_response.results)
                
                for domain_name, goals in domain_goals.items():
                    focus_str = "general"
                    try:
                        focus = FocusArea(focus_str)
                    except ValueError:
                        focus = FocusArea.GENERAL
                    
                    importance = len(goals) / total_goals if total_goals > 0 else 0.5
                    
                    # Determine domain status from actual goal states
                    goal_statuses = [g.succeeded for g in goals]
                    failed_count = sum(1 for g in goals if not g.succeeded and not g.skipped)
                    completed_count = sum(1 for g in goals if g.succeeded)
                    skipped_count = sum(1 for g in goals if g.skipped)
                    running_count = 0  # All goals in BrainResponse are terminal
                    
                    if failed_count > 0 and completed_count > 0:
                        status = "partial"
                    elif completed_count == len(goals):
                        status = "completed"
                    elif failed_count > 0 and completed_count == 0:
                        status = "failed"
                    elif skipped_count > 0:
                        status = "skipped"
                    else:
                        status = "completed"
                    
                    # Get capability IDs for this domain
                    domain_caps = tuple(g.capability_id for g in goals)
                    
                    domains.append(DomainInfo(
                        name=domain_name,
                        focus=focus,
                        importance=importance,
                        status=status,
                        capability_ids=domain_caps,
                    ))
                
                # Sort by importance descending
                domains.sort(key=lambda d: d.importance, reverse=True)
                return tuple(domains)
        
        # Fallback to heuristic-based detection
        activity = metadata.get("activity", {})
        active_domains = activity.get("active_domains", [])
        
        if not active_domains:
            return ()
        
        domains = []
        total_tasks = sum(d.get("task_count", 0) for d in active_domains)
        
        for domain_info in active_domains:
            domain_name = domain_info.get("context", "unknown")
            focus_str = domain_info.get("focus", "general")
            task_count = domain_info.get("task_count", 0)
            
            # Map focus string to FocusArea
            try:
                focus = FocusArea(focus_str)
            except ValueError:
                focus = FocusArea.GENERAL
            
            # Importance based on task count proportion
            importance = task_count / total_tasks if total_tasks > 0 else 0.5
            
            # Determine status from task counts (simplified)
            status = "running"  # default
            
            # Get capability IDs for this domain from active_semantic_capabilities
            active_caps = activity.get("active_semantic_capabilities", [])
            domain_caps = tuple(cap for cap in active_caps if cap.startswith(domain_name + "."))
            
            # Determine domain category from first capability
            domain_category = None
            if domain_caps:
                cap_def = self._capability_registry.get(domain_caps[0]) if self._capability_registry.contains(domain_caps[0]) else None
                if cap_def:
                    domain_category = cap_def.category.value
            
            domains.append(DomainInfo(
                name=domain_name,
                focus=focus,
                importance=importance,
                status=status,
                capability_ids=domain_caps,
                domain_category=domain_category,
                primary_entities=(),
                primary_topics=(),
            ))
        
        # Sort by importance descending
        domains.sort(key=lambda d: d.importance, reverse=True)
        return tuple(domains)
    
    def _compute_synthesis(self, metadata: MappingProxyType[str, Any]) -> SynthesisInfo | None:
        """Compute synthesis goal information from metadata."""
        # If we have a real BrainResponse, use its authoritative data
        if self._brain is not None:
            brain_response = self._brain.last_response
            if brain_response is not None and brain_response.synthesis_goal_id is not None:
                # Find the synthesis goal result
                synthesis_result = None
                for result in brain_response.results:
                    if result.goal_id == brain_response.synthesis_goal_id:
                        synthesis_result = result
                        break
                
                if synthesis_result is not None:
                    # Get dependencies from the synthesis goal's actual depends_on
                    depends_on = synthesis_result.depends_on
                    completed_deps = ()
                    failed_deps = ()
                    
                    # Build completed/failed dependencies from actual goal results
                    for result in brain_response.results:
                        if result.goal_id in depends_on:
                            if result.succeeded:
                                completed_deps += (result.goal_id,)
                            else:
                                failed_deps += (result.goal_id,)
                    
                    # Determine synthesis status
                    if synthesis_result.succeeded:
                        synth_status = "completed"
                    elif synthesis_result.skipped:
                        synth_status = "skipped"
                    else:
                        synth_status = "failed"
                    
                    return SynthesisInfo(
                        goal_id=brain_response.synthesis_goal_id,
                        capability_id=synthesis_result.capability_id,
                        status=synth_status,
                        depends_on=depends_on,
                        completed_dependencies=completed_deps,
                        failed_dependencies=failed_deps,
                    )
        
        # Fallback to heuristic-based detection
        activity = metadata.get("activity", {})
        active_capabilities = activity.get("active_capabilities", [])
        
        # Check if there's a synthesis capability (chat.respond)
        synthesis_caps = [cap for cap in active_capabilities if cap == "chat.respond"]
        if not synthesis_caps:
            return None
        
        # Determine synthesis status from brain tracking or task status
        if self._brain_execution_active:
            # Check if synthesis goal is running
            if self._brain_synthesis_goal_id and self._brain_synthesis_goal_id in self._brain_goals:
                synth_status = self._brain_goals[self._brain_synthesis_goal_id].get("status", "pending")
            else:
                synth_status = "waiting"
        elif self._brain_execution_succeeded is not None:
            if self._brain_execution_succeeded:
                synth_status = "completed"
            else:
                synth_status = "failed"
        else:
            # Check task status for chat.respond
            tasks = self._task_manager.get_all()
            chat_respond_task = None
            for task in tasks.values():
                if task.request.capability_id == "chat.respond":
                    chat_respond_task = task
                    break
            
            if chat_respond_task:
                task_status = chat_respond_task.status.name
                if task_status == "RUNNING":
                    synth_status = "running"
                elif task_status in ("PENDING", "WAITING"):
                    synth_status = "waiting"
                elif task_status == "COMPLETED":
                    synth_status = "completed"
                elif task_status == "FAILED":
                    synth_status = "failed"
                else:
                    synth_status = "pending"
            else:
                synth_status = "pending"
        
        # Get dependencies from metadata (simplified)
        depends_on = ()
        completed_deps = ()
        failed_deps = ()
        
        # Determine synthesis domain and semantic type
        synthesis_domain, synthesis_semantic_type, _, _ = self._get_semantic_info_from_capability("chat.respond")
        
        # Get dependency domains from active capabilities
        dependency_domains = ()
        active_caps = activity.get("active_semantic_capabilities", [])
        for cap in active_caps:
            if cap != "chat.respond":
                dep_domain, _, _, _ = self._get_semantic_info_from_capability(cap)
                if dep_domain:
                    dependency_domains += (dep_domain,)
        
        return SynthesisInfo(
            goal_id=self._brain_synthesis_goal_id,
            capability_id="chat.respond",
            status=synth_status,
            depends_on=depends_on,
            completed_dependencies=completed_deps,
            failed_dependencies=failed_deps,
            domain=synthesis_domain,
            semantic_type=synthesis_semantic_type,
            dependency_domains=dependency_domains,
        )
    
    def _compute_dependencies(self, metadata: MappingProxyType[str, Any]) -> tuple[DependencyInfo, ...]:
        """Compute dependency relationships from metadata."""
        # If we have a real BrainResponse, use its authoritative goal results
        if self._brain is not None:
            brain_response = self._brain.last_response
            if brain_response is not None:
                deps = []
                for result in brain_response.results:
                    # Determine status from GoalResult
                    if result.skipped:
                        status = "skipped"
                    elif result.succeeded:
                        status = "completed"
                    else:
                        status = "failed"
                    
                    # Determine if this is the synthesis goal
                    is_synthesis = (brain_response.synthesis_goal_id == result.goal_id)
                    
                    # Get depends_on from the actual GoalResult
                    depends_on = result.depends_on
                    
                    # Use actual capability_id from GoalResult
                    capability_id = result.capability_id
                    
                    deps.append(DependencyInfo(
                        goal_id=result.goal_id,
                        capability_id=capability_id,
                        depends_on=depends_on,
                        status=status,
                        is_synthesis=is_synthesis,
                    ))
                return tuple(deps)
        
        # Fallback to heuristic-based detection
        activity = metadata.get("activity", {})
        active_semantic_capabilities = activity.get("active_semantic_capabilities", [])
        
        if not active_semantic_capabilities:
            return ()
        
        # Build dependency info from tracked brain goals
        deps = []
        for goal_id, goal_info in self._brain_goals.items():
            capability_id = goal_info.get("capability_id", "unknown")
            status = goal_info.get("status", "pending")
            
            # Determine if this is a synthesis goal
            is_synthesis = (capability_id == "chat.respond")
            
            # Get depends_on from tracking
            depends_on = goal_info.get('depends_on', ())
            
            # Get semantic info from capability registry
            domain, semantic_type, category, tags = self._get_semantic_info_from_capability(capability_id)
            
            # Get dependency domains
            dependency_domains = ()
            for dep_id in depends_on:
                dep_goal_info = self._brain_goals.get(dep_id, {})
                dep_cap_id = dep_goal_info.get("capability_id", "")
                if dep_cap_id:
                    dep_domain, _, _, _ = self._get_semantic_info_from_capability(dep_cap_id)
                    if dep_domain:
                        dependency_domains += (dep_domain,)
            
            deps.append(DependencyInfo(
                goal_id=goal_id,
                capability_id=capability_id,
                depends_on=depends_on,
                status=status,
                is_synthesis=is_synthesis,
                domain=domain,
                semantic_type=semantic_type,
                capability_category=category,
                capability_tags=tags,
                dependency_domains=dependency_domains,
            ))
        
        return tuple(deps)
    
    def _infer_context_from_capability(
        self,
        capability_id: str,
        capability_def: Any | None,
    ) -> tuple[str, FocusArea, float]:
        """Infer semantic context, focus, and confidence from capability."""
        # Map capability IDs to semantic contexts
        capability_lower = capability_id.lower()
        
        # Weather capabilities
        if "weather" in capability_lower:
            if "forecast" in capability_lower:
                return "weather", FocusArea.FORECAST, 0.95
            return "weather", FocusArea.CURRENT_CONDITIONS, 0.95
        
        # Expense capabilities
        if "expense" in capability_lower:
            if "summarize" in capability_lower or "monthly" in capability_lower:
                return "expense", FocusArea.MONTHLY_SUMMARY, 0.95
            return "expense", FocusArea.GENERAL, 0.9
        
        # Finance capabilities
        if "finance" in capability_lower or "exchange" in capability_lower or "currency" in capability_lower:
            return "finance", FocusArea.GENERAL, 0.9
        
        # Media capabilities
        if "media" in capability_lower:
            return "media", FocusArea.PLAYBACK, 0.95
        
        # Chat capabilities
        if "chat" in capability_lower:
            return "chat", FocusArea.GENERAL, 0.9
        
        # File capabilities
        if "filesystem" in capability_lower or "file" in capability_lower:
            return "file", FocusArea.FILE_BROWSER, 0.9
        
        # Code capabilities
        if "code" in capability_lower or "coding" in capability_lower:
            return "code", FocusArea.CODE_EDITOR, 0.9
        
        # Document capabilities
        if "document" in capability_lower or "pdf" in capability_lower:
            return "document", FocusArea.DOCUMENT_VIEWER, 0.9
        
        # Vision capabilities
        if "vision" in capability_lower or "image" in capability_lower:
            if "video" in capability_lower:
                return "video", FocusArea.VIDEO_PLAYER, 0.85
            return "image", FocusArea.IMAGE_VIEWER, 0.85
        
        # Video capabilities (standalone video generation/editing)
        if "video" in capability_lower:
            return "video", FocusArea.VIDEO_PLAYER, 0.85
        
        # News capabilities
        if "news" in capability_lower:
            return "news", FocusArea.SEARCH_RESULTS, 0.9
        
        # Voice capabilities
        if "voice" in capability_lower or "speech" in capability_lower:
            return "voice", FocusArea.VOICE_INPUT, 0.9
        
        # Search capabilities
        if "search" in capability_lower or "web" in capability_lower:
            return "search", FocusArea.SEARCH_RESULTS, 0.8
        
        # Use capability category if available
        if capability_def is not None:
            category = capability_def.category.value.lower()
            if category in ("tool", "automation", "workflow"):
                return category, FocusArea.GENERAL, 0.7
        
        # Default
        return "system", FocusArea.GENERAL, 0.5
    
    def _context_type_to_semantic(self, context_type: str) -> str:
        """Map ContextType to semantic context name."""
        mapping = {
            "interaction": "chat",
            "module": "system",
            "scheduled": "system",
            "system": "system",
            "task": "task",
            "tool": "tool",
            "workflow": "workflow",
        }
        return mapping.get(context_type, "system")
    
    def _attention_from_task_status(self, status: str) -> AttentionLevel:
        """Map task status to attention level."""
        if status == "RUNNING":
            return AttentionLevel.PRIMARY
        elif status in ("PENDING", "PAUSED", "WAITING"):
            return AttentionLevel.SECONDARY
        elif status == "COMPLETED":
            return AttentionLevel.SECONDARY  # Completed but parent still active
        return AttentionLevel.AMBIENT
    
    def _determine_urgency(self) -> UrgencyLevel:
        """Determine urgency from system signals."""
        # Check lifecycle state
        lifecycle = self._state_manager.get_lifecycle_state()
        if lifecycle.name == "STOPPING":
            return UrgencyLevel.CRITICAL
        
        # Check provider state
        provider_state = self._state_manager.get_provider_state()
        if provider_state.name == "DISCONNECTED":
            return UrgencyLevel.ELEVATED
        
        # Check for failed tasks
        tasks = self._task_manager.get_all()
        failed_tasks = [t for t in tasks.values() if t.status.name == "FAILED"]
        if failed_tasks:
            return UrgencyLevel.ELEVATED
        
        return UrgencyLevel.NORMAL
    
    def _build_surfaces_for_context(self, context: str, active_capability_ids: set[str] | None = None, brain_goal_results: dict[str, 'GoalResult'] | None = None, synthesis_goal_id: str | None = None) -> tuple[SurfaceItem, ...]:
        """Build semantic surfaces for a given context."""
        surfaces = []
        
        # Define semantic surfaces per context
        context_surfaces = {
            "weather": [
                ("weather.current", "Current Conditions", SurfaceTier.PRIMARY),
                ("weather.forecast", "Forecast", SurfaceTier.PRIMARY),
                ("weather.location", "Location", SurfaceTier.SECONDARY),
            ],
            "expense": [
                ("expense.add", "Add Expense", SurfaceTier.PRIMARY),
                ("expense.list", "List Expenses", SurfaceTier.PRIMARY),
                ("expense.summarize", "Monthly Summary", SurfaceTier.SECONDARY),
                ("expense.compare", "Compare Periods", SurfaceTier.SECONDARY),
            ],
            "media": [
                ("media.play", "Play", SurfaceTier.PRIMARY),
                ("media.pause", "Pause", SurfaceTier.PRIMARY),
                ("media.get_state", "Playback State", SurfaceTier.PRIMARY),
                ("media.queue", "Queue", SurfaceTier.SECONDARY),
            ],
            "chat": [
                ("chat.respond", "Chat", SurfaceTier.PRIMARY),
            ],
            "file": [
                ("filesystem.read", "Read File", SurfaceTier.PRIMARY),
                ("filesystem.write", "Write File", SurfaceTier.PRIMARY),
                ("filesystem.list", "List Directory", SurfaceTier.SECONDARY),
            ],
            "code": [
                ("coding.analyze", "Analyze Code", SurfaceTier.PRIMARY),
                ("coding.edit", "Edit Code", SurfaceTier.PRIMARY),
                ("coding.search", "Search Code", SurfaceTier.SECONDARY),
            ],
            "document": [
                ("document.read_pdf", "Read PDF", SurfaceTier.PRIMARY),
                ("document.extract_text", "Extract Text", SurfaceTier.PRIMARY),
                ("ocr.extract_text", "OCR Extract", SurfaceTier.SECONDARY),
            ],
            "image": [
                ("vision.describe_image", "Describe Image", SurfaceTier.PRIMARY),
                ("vision.detect_objects", "Detect Objects", SurfaceTier.SECONDARY),
            ],
            "video": [
                ("video.generate", "Generate Video", SurfaceTier.PRIMARY),
                ("video.edit", "Edit Video", SurfaceTier.SECONDARY),
            ],
            "voice": [
                ("voice.speech_to_text", "Speech to Text", SurfaceTier.PRIMARY),
                ("voice.text_to_speech", "Text to Speech", SurfaceTier.SECONDARY),
            ],
            "news": [
                ("news.latest", "Latest News", SurfaceTier.PRIMARY),
                ("news.search", "Search News", SurfaceTier.PRIMARY),
                ("news.topic", "Topic News", SurfaceTier.SECONDARY),
            ],
            "search": [
                ("web.search", "Web Search", SurfaceTier.PRIMARY),
            ],
            "system": [
                ("runtime.info", "Runtime Info", SurfaceTier.AMBIENT),
                ("system.status", "System Status", SurfaceTier.AMBIENT),
            ],
        }
        
        surface_defs = context_surfaces.get(context, context_surfaces["system"])
        
        for cap_id, label, tier in surface_defs:
            # Only include if capability exists
            if self._capability_registry.contains(cap_id):
                metadata = self._build_surface_metadata(cap_id, brain_goal_results, synthesis_goal_id)
                # Get semantic info from capability registry
                domain, semantic_type, category, tags = self._get_semantic_info_from_capability(cap_id)
                surfaces.append(SurfaceItem(
                    capability_id=cap_id,
                    label=label,
                    tier=tier,
                    metadata=metadata,
                    domain=domain,
                    semantic_type=semantic_type,
                    capability_category=category,
                    capability_tags=tags,
                ))
        
        # Include actively executing semantic capabilities from concurrent tasks
        if active_capability_ids:
            for cap_id in sorted(active_capability_ids):
                # Skip if already in surfaces
                if any(s.capability_id == cap_id for s in surfaces):
                    continue
                # Only include if capability exists in registry
                if self._capability_registry.contains(cap_id):
                    cap_def = self._capability_registry.get(cap_id)
                    # Use capability name from registry or derive from ID
                    label = cap_def.name if cap_def else cap_id.replace(".", " ").title()
                    # Determine tier: PRIMARY if it's the primary context's domain, SECONDARY otherwise
                    tier = SurfaceTier.SECONDARY
                    metadata = self._build_surface_metadata(cap_id, brain_goal_results, synthesis_goal_id)
                    # Get semantic info from capability registry
                    domain, semantic_type, category, tags = self._get_semantic_info_from_capability(cap_id)
                    surfaces.append(SurfaceItem(
                        capability_id=cap_id,
                        label=label,
                        tier=tier,
                        metadata=metadata,
                        domain=domain,
                        semantic_type=semantic_type,
                        capability_category=category,
                        capability_tags=tags,
                    ))
        
        # Always add ambient system surfaces
        for cap_id, label, tier in context_surfaces["system"]:
            if self._capability_registry.contains(cap_id):
                # Avoid duplicates
                if not any(s.capability_id == cap_id for s in surfaces):
                    domain, semantic_type, category, tags = self._get_semantic_info_from_capability(cap_id)
                    surfaces.append(SurfaceItem(
                        capability_id=cap_id,
                        label=label,
                        tier=tier,
                        metadata=MappingProxyType({}),
                        domain=domain,
                        semantic_type=semantic_type,
                        capability_category=category,
                        capability_tags=tags,
                    ))
        
        return tuple(surfaces)
    
    def _get_semantic_info_from_capability(self, capability_id: str) -> tuple[str | None, str | None, str | None, tuple[str, ...]]:
        """Extract semantic information from capability registry.
        
        Returns:
            tuple of (domain, semantic_type, category, tags)
        """
        if not self._capability_registry.contains(capability_id):
            return None, None, None, ()
        
        cap_def = self._capability_registry.get(capability_id)
        if cap_def is None:
            return None, None, None, ()
        
        # Extract domain from tags (first non-network/tool tag)
        domain = None
        for tag in cap_def.tags:
            if tag not in ("network", "tool", "local", "llm"):
                domain = tag
                break
        
        # Extract semantic type from capability_id (part after domain)
        semantic_type = None
        if "." in capability_id:
            parts = capability_id.split(".", 1)
            if len(parts) > 1:
                semantic_type = parts[1].replace("_", " ")
        
        category = cap_def.category.value if cap_def.category else None
        tags = tuple(cap_def.tags)
        
        return domain, semantic_type, category, tags
    
    def _build_surface_metadata(self, capability_id: str, brain_goal_results: dict[str, 'GoalResult'] | None, synthesis_goal_id: str | None = None) -> MappingProxyType[str, Any]:
        """Build semantic metadata for a surface item from authoritative GoalResult."""
        if brain_goal_results is None:
            return MappingProxyType({})
        
        # Find the GoalResult for this capability
        goal_result = None
        for result in brain_goal_results.values():
            if result.capability_id == capability_id:
                goal_result = result
                break
        
        if goal_result is None:
            return MappingProxyType({})
        
        # Build metadata from authoritative GoalResult
        metadata_dict = {
            "status": "completed" if goal_result.succeeded else ("skipped" if goal_result.skipped else "failed"),
            "domain": self._infer_context_from_capability(capability_id, None)[0],
            "execution_state": "completed" if goal_result.succeeded else ("skipped" if goal_result.skipped else "failed"),
            "result_available": goal_result.succeeded and goal_result.response is not None,
            "is_synthesis": goal_result.goal_id == synthesis_goal_id,
        }
        
        # Add dependency information if available
        if hasattr(goal_result, 'depends_on') and goal_result.depends_on:
            metadata_dict["depends_on"] = goal_result.depends_on
        
        return MappingProxyType(metadata_dict)
    
    # ============================================================
    # Phase 2: Contextual Intelligence Computation Methods
    # ============================================================
    
    def _compute_user_intent(
        self,
        candidate: _ContextCandidate,
        brain_response: 'BrainResponse | None' = None,
    ) -> UserIntent:
        """
        Derive user intent from existing structured execution state.
        
        DOES NOT use LLM classification - derives deterministically from:
        - Active capabilities and their categories
        - Goal dependencies (synthesis vs data gathering)
        - Request patterns
        """
        # Check if we have a synthesis goal with dependencies
        if brain_response and brain_response.synthesis_goal_id:
            # Synthesis implies the user wants a comprehensive response
            return UserIntent.REQUESTING_INFORMATION
        
        # Check active capabilities
        metadata = candidate.metadata
        activity = metadata.get("activity", {})
        active_semantic_caps = activity.get("active_semantic_capabilities", [])
        active_all_caps = activity.get("active_capabilities", [])
        
        # Check for research-like patterns (multiple data gathering capabilities)
        data_gathering_domains = {"weather", "finance", "search", "news", "web"}
        active_domains = set()
        for cap in active_semantic_caps:
            domain = cap.split(".")[0] if "." in cap else cap
            active_domains.add(domain)
        
        if len(active_domains & data_gathering_domains) >= 2:
            return UserIntent.RESEARCHING
        
        # Check for creation (file write, code edit, expense add)
        creation_caps = {"filesystem.write", "coding.edit", "expense.add", "media.play"}
        if any(cap in active_semantic_caps for cap in creation_caps):
            return UserIntent.CREATING
        
        # Check for execution actions (shell, file operations)
        execution_caps = {"shell.execute", "filesystem.read", "filesystem.list"}
        if any(cap in active_semantic_caps for cap in execution_caps):
            return UserIntent.EXECUTING_ACTION
        
        # Check for communication (chat.respond without deps, voice)
        communication_caps = {"chat.respond", "voice.text_to_speech"}
        if any(cap in active_semantic_caps for cap in communication_caps):
            if not (brain_response and brain_response.synthesis_goal_id):
                return UserIntent.COMMUNICATING
        
        # Check for monitoring (system.status, runtime.info - recurring system checks)
        # weather.current is NOT monitoring - it's a one-time information request
        monitoring_caps = {"system.status", "runtime.info"}
        if any(cap in active_all_caps for cap in monitoring_caps) and len(active_semantic_caps) <= 1:
            return UserIntent.MONITORING
        
        # Default: requesting information
        if active_semantic_caps:
            return UserIntent.REQUESTING_INFORMATION
        
        return UserIntent.UNKNOWN
    
    def _compute_conversational_context(
        self,
        candidate: _ContextCandidate,
        previous_state: UIContextState | None,
        source_event: Any = None,
    ) -> ConversationalContext:
        """
        Compute conversational continuity across turns.
        
        Uses existing session state and turn information.
        Does NOT expose raw conversation history.
        """
        current_domain = candidate.context if candidate.context != "system" else None
        
        # Use conversational context's current_domain as previous_domain when available
        # This tracks the last meaningful domain, not intermediate recomputation states
        previous_domain = None
        if previous_state and previous_state.conversational_context:
            previous_domain = previous_state.conversational_context.current_domain
        elif previous_state and previous_state.context != "system":
            previous_domain = previous_state.context
        
        # Track the last non-system domain for previous_domain when current becomes system
        if current_domain is None and previous_state and previous_state.conversational_context:
            previous_domain = previous_state.conversational_context.current_domain
        
        # Detect if previous_state represents an internal recomputation
        # (context differs from conversational_context's current_domain)
        internal_recomputation = False
        if (previous_state and previous_state.conversational_context and 
            previous_state.context != "system" and
            previous_state.context != previous_state.conversational_context.current_domain):
            internal_recomputation = True
        
        # Determine transition type
        transition = ContextTransition.NONE
        if previous_state is None:
            transition = ContextTransition.ENTERED
        elif previous_domain != current_domain:
            if previous_domain is None:
                transition = ContextTransition.ENTERED
            elif current_domain is None:
                transition = ContextTransition.BECAME_AMBIENT
            else:
                transition = ContextTransition.CHANGED
        else:
            # Same domain - preserve previous transition if it was a meaningful change
            # Only update to EXPANDED/NARROWED if domains actually expanded/narrowed
            # Otherwise keep NONE (no new transition)
            prev_domains = {d.name for d in previous_state.domains}
            curr_domains = set()
            activity = candidate.metadata.get("activity", {})
            active_domains = activity.get("active_domains", [])
            curr_domains = {d.get("context") for d in active_domains if d.get("context")}
            
            if curr_domains > prev_domains:
                transition = ContextTransition.EXPANDED
            elif curr_domains < prev_domains:
                transition = ContextTransition.NARROWED
            else:
                # Domain unchanged - preserve previous transition if it was ENTERED/CHANGED
                # This prevents internal events from resetting the transition
                if previous_state.conversational_context and previous_state.conversational_context.contextual_transition in (ContextTransition.ENTERED, ContextTransition.CHANGED):
                    transition = previous_state.conversational_context.contextual_transition
                else:
                    transition = ContextTransition.NONE
        
        # If this is an internal recomputation (domain changed but previous_state was internal),
        # don't update the conversational context's current_domain - keep the last meaningful one
        effective_current_domain = current_domain
        if internal_recomputation and previous_state and previous_state.conversational_context:
            effective_current_domain = previous_state.conversational_context.current_domain
        
        # Build active subject from primary capability
        active_subject = None
        if candidate.context not in ("system", "chat", "voice"):
            # Try to extract subject from task metadata
            task_info = candidate.metadata.get("task", {})
            cap_id = task_info.get("capability_id", "")
            if cap_id:
                active_subject = f"{candidate.context}: {cap_id}"
        
        # Ongoing task from brain execution state
        ongoing_task = None
        if self._brain_execution_active:
            ongoing_task = f"Processing {len(self._brain_goals)} goals"
        elif self._brain_execution_succeeded is not None:
            if self._brain_execution_succeeded:
                ongoing_task = "Request completed"
            else:
                ongoing_task = "Request failed"
        
        # Turn count from metadata or estimate
        turn_count = 0
        if previous_state and previous_state.conversational_context:
            turn_count = previous_state.conversational_context.turn_count + 1
        elif previous_state:
            turn_count = 1
        
        # Last user request (truncated)
        last_user_request = None
        # This would come from the interaction state or session
        # For now, we can extract from task metadata if available
        
        return ConversationalContext(
            current_domain=effective_current_domain,
            active_subject=active_subject,
            ongoing_task=ongoing_task,
            previous_domain=previous_domain,
            turn_count=turn_count,
            last_user_request=last_user_request,
            contextual_transition=transition,
        )
    
    def _compute_entities(
        self,
        candidate: _ContextCandidate,
        brain_response: 'BrainResponse | None' = None,
    ) -> tuple[EntityInfo, ...]:
        """
        Extract structured entities from existing context.
        
        Does NOT create new entity extraction - uses existing structured data from:
        - Task inputs (location, currency codes, dates)
        - Goal results (returned data)
        - Memory/Knowledge context
        """
        entities = []
        
        # Extract from task metadata (inputs to capabilities)
        activity = candidate.metadata.get("activity", {})
        active_semantic_caps = activity.get("active_semantic_capabilities", [])
        
        # We need to get actual task inputs from TaskManager
        # For now, extract from known patterns in capability IDs and metadata
        
        # Check brain response for actual goal inputs/results
        if brain_response:
            for result in brain_response.results:
                if result.succeeded and result.response:
                    outputs = result.response.outputs
                    # Extract entities from result data
                    entities.extend(self._extract_entities_from_result(
                        result.capability_id, outputs
                    ))
        
        # Extract from task manager tasks (inputs)
        tasks = self._task_manager.get_all()
        for task in tasks.values():
            inputs = task.request.inputs
            if isinstance(inputs, (dict, MappingProxyType)):
                entities.extend(self._extract_entities_from_inputs(
                    task.request.capability_id, dict(inputs)
                ))
        
        # Deduplicate by name+type+domain
        seen = set()
        unique_entities = []
        for entity in entities:
            key = (entity.name, entity.entity_type, entity.domain)
            if key not in seen:
                seen.add(key)
                unique_entities.append(entity)
        
        return tuple(unique_entities)
    
    def _extract_entities_from_inputs(
        self,
        capability_id: str,
        inputs: dict[str, Any],
    ) -> list[EntityInfo]:
        """Extract entities from capability inputs."""
        entities = []
        domain, _, _ = self._infer_context_from_capability(capability_id, None)
        
        # Location entities
        if "location" in inputs:
            loc = inputs["location"]
            if isinstance(loc, str) and loc.strip():
                entities.append(EntityInfo(
                    name=loc.strip(),
                    entity_type=EntityType.LOCATION,
                    domain=domain,
                    confidence=0.9,
                    metadata=MappingProxyType({"source": "task_input"}),
                ))
        
        # Currency entities
        for currency_field in ("from", "to", "currency", "base", "target"):
            if currency_field in inputs:
                curr = inputs[currency_field]
                if isinstance(curr, str) and curr.strip():
                    entities.append(EntityInfo(
                        name=curr.strip().upper(),
                        entity_type=EntityType.CURRENCY,
                        domain=domain,
                        confidence=0.9,
                        metadata=MappingProxyType({"source": "task_input", "field": currency_field}),
                    ))
        
        # Date/time entities
        for date_field in ("date", "start_date", "end_date", "days", "time"):
            if date_field in inputs:
                val = inputs[date_field]
                if isinstance(val, (str, int)) and str(val).strip():
                    entities.append(EntityInfo(
                        name=str(val).strip(),
                        entity_type=EntityType.DATE_TIME,
                        domain=domain,
                        confidence=0.8,
                        metadata=MappingProxyType({"source": "task_input", "field": date_field}),
                    ))
        
        # Query/search entities
        if "query" in inputs or "search" in inputs or "topic" in inputs:
            query = inputs.get("query") or inputs.get("search") or inputs.get("topic")
            if isinstance(query, str) and query.strip():
                entities.append(EntityInfo(
                    name=query.strip()[:100],  # Truncate long queries
                    entity_type=EntityType.TOPIC,
                    domain=domain,
                    confidence=0.7,
                    metadata=MappingProxyType({"source": "task_input", "field": "query"}),
                ))
        
        # Amount/measurement entities
        if "amount" in inputs:
            amt = inputs["amount"]
            if isinstance(amt, (int, float)):
                entities.append(EntityInfo(
                    name=str(amt),
                    entity_type=EntityType.MEASUREMENT,
                    domain=domain,
                    confidence=0.8,
                    metadata=MappingProxyType({"source": "task_input", "field": "amount"}),
                ))
        
        return entities
    
    def _extract_entities_from_result(
        self,
        capability_id: str,
        outputs: dict[str, Any],
    ) -> list[EntityInfo]:
        """Extract entities from capability result outputs."""
        entities = []
        domain, _, _ = self._infer_context_from_capability(capability_id, None)
        
        # For weather results, extract location
        if "weather" in capability_id:
            if "location" in outputs:
                loc = outputs["location"]
                if isinstance(loc, str) and loc.strip():
                    entities.append(EntityInfo(
                        name=loc.strip(),
                        entity_type=EntityType.LOCATION,
                        domain=domain,
                        confidence=0.95,
                        metadata=MappingProxyType({"source": "goal_result"}),
                    ))
            # Temperature, condition as measurements
            for field in ("temp", "temperature", "condition", "humidity"):
                if field in outputs:
                    val = outputs[field]
                    if val is not None:
                        entities.append(EntityInfo(
                            name=f"{field}: {val}",
                            entity_type=EntityType.MEASUREMENT,
                            domain=domain,
                            confidence=0.85,
                            metadata=MappingProxyType({"source": "goal_result", "field": field}),
                        ))
        
        # For finance results, extract currencies and rates
        if "finance" in capability_id or "exchange" in capability_id or "currency" in capability_id:
            for field in ("from", "to", "base", "target", "rate", "amount"):
                if field in outputs:
                    val = outputs[field]
                    if isinstance(val, str) and val.strip():
                        entities.append(EntityInfo(
                            name=val.strip().upper(),
                            entity_type=EntityType.CURRENCY if field in ("from", "to", "base", "target") else EntityType.MEASUREMENT,
                            domain=domain,
                            confidence=0.9,
                            metadata=MappingProxyType({"source": "goal_result", "field": field}),
                        ))
                    elif isinstance(val, (int, float)):
                        entities.append(EntityInfo(
                            name=str(val),
                            entity_type=EntityType.MEASUREMENT,
                            domain=domain,
                            confidence=0.85,
                            metadata=MappingProxyType({"source": "goal_result", "field": field}),
                        ))
        
        # For web search, extract topics from results
        if "web.search" in capability_id or "news" in capability_id:
            if "results" in outputs:
                results = outputs["results"]
                if isinstance(results, list):
                    for i, result in enumerate(results[:3]):  # Top 3 results
                        if isinstance(result, str) and result.strip():
                            # Extract key terms (simplified)
                            words = result.split()[:10]
                            topic_name = " ".join(words)
                            entities.append(EntityInfo(
                                name=topic_name[:100],
                                entity_type=EntityType.TOPIC,
                                domain=domain,
                                confidence=0.6,
                                metadata=MappingProxyType({"source": "goal_result", "result_index": i}),
                            ))
        
        return entities
    
    def _compute_topics(
        self,
        candidate: _ContextCandidate,
        brain_response: 'BrainResponse | None' = None,
    ) -> tuple[TopicInfo, ...]:
        """
        Compute semantic topics from existing structured data.
        
        Uses:
        - Active domains from goals/capabilities
        - Capability categories
        - Memory/Knowledge context (if available)
        Does NOT introduce new topic modeling.
        """
        topics = []
        
        # Get topics from active domains
        activity = candidate.metadata.get("activity", {})
        active_domains = activity.get("active_domains", [])
        
        for domain_info in active_domains:
            domain_name = domain_info.get("context", "")
            if not domain_name:
                continue
            
            # Map domain to semantic topic
            topic_name = self._map_domain_to_topic(domain_name)
            if topic_name:
                topics.append(TopicInfo(
                    name=topic_name,
                    domain=domain_name,
                    relevance=domain_info.get("task_count", 1) / max(1, sum(d.get("task_count", 1) for d in active_domains)),
                    source="capability",
                ))
        
        # Add synthesis as a topic if present
        if brain_response and brain_response.synthesis_goal_id:
            topics.append(TopicInfo(
                name="synthesis",
                domain="chat",
                relevance=0.9,
                source="goal",
            ))
        
        # Deduplicate
        seen = set()
        unique_topics = []
        for topic in topics:
            key = (topic.name, topic.domain)
            if key not in seen:
                seen.add(key)
                unique_topics.append(topic)
        
        return tuple(unique_topics)
    
    def _map_domain_to_topic(self, domain: str) -> str | None:
        """Map capability domain to semantic topic."""
        domain_lower = domain.lower()
        
        topic_mapping = {
            "weather": "weather",
            "expense": "finance",
            "finance": "finance",
            "currency": "finance",
            "exchange": "finance",
            "media": "media",
            "chat": "communication",
            "file": "filesystem",
            "filesystem": "filesystem",
            "code": "coding",
            "coding": "coding",
            "document": "document",
            "pdf": "document",
            "ocr": "document",
            "vision": "image",
            "image": "image",
            "video": "video",
            "voice": "voice",
            "speech": "voice",
            "news": "current_events",
            "search": "research",
            "web": "research",
        }
        
        return topic_mapping.get(domain_lower, domain_lower)
    
    def _compute_semantic_relevance(
        self,
        candidate: _ContextCandidate,
        brain_response: 'BrainResponse | None' = None,
    ) -> tuple[SemanticRelevance, ...]:
        """
        Compute semantic relevance scores for active domains.
        
        Based on deterministic signals:
        - Current user request (primary domain)
        - Active execution (running tasks)
        - Dependency relationships (synthesis dependencies)
        - Request status (failed goals may be more relevant for visibility)
        - Recency
        - Domain continuity
        """
        relevance_scores = []
        
        activity = candidate.metadata.get("activity", {})
        active_domains = activity.get("active_domains", [])
        task_counts = activity.get("task_counts", {})
        
        total_tasks = sum(d.get("task_count", 0) for d in active_domains)
        if total_tasks == 0:
            total_tasks = 1
        
        for domain_info in active_domains:
            domain_name = domain_info.get("context", "")
            if not domain_name:
                continue
            
            task_count = domain_info.get("task_count", 0)
            signals = []
            score = 0.0
            
            # Signal 1: Primary context domain gets base relevance
            if domain_name == candidate.context:
                score += 0.4
                signals.append("primary_context")
            
            # Signal 2: Task proportion
            task_proportion = task_count / total_tasks
            score += task_proportion * 0.3
            if task_proportion > 0:
                signals.append(f"task_proportion_{task_proportion:.1f}")
            
            # Signal 3: Has running tasks
            running_count = task_counts.get("running", 0)
            if running_count > 0:
                score += 0.1
                signals.append("has_running_tasks")
            
            # Signal 4: Has failed tasks (higher visibility needed)
            failed_count = task_counts.get("failed", 0)
            if failed_count > 0:
                score += 0.15
                signals.append("has_failed_tasks")
            
            # Signal 5: Is synthesis dependency
            if brain_response and brain_response.synthesis_goal_id:
                for result in brain_response.results:
                    if result.goal_id == brain_response.synthesis_goal_id:
                        if domain_name in [self._infer_context_from_capability(dep_id.split("-")[0] if "-" in dep_id else dep_id, None)[0] 
                                          for dep_id in result.depends_on]:
                            score += 0.1
                            signals.append("synthesis_dependency")
            
            # Signal 6: Domain continuity (same as previous turn)
            # This would be checked against previous state
            
            # Clamp score
            score = min(1.0, score)
            
            relevance_scores.append(SemanticRelevance(
                domain=domain_name,
                score=score,
                signals=tuple(signals),
            ))
        
        # Sort by score descending
        relevance_scores.sort(key=lambda r: r.score, reverse=True)
        
        return tuple(relevance_scores)
    
    def _compute_freshness(
        self,
        candidate: _ContextCandidate,
        brain_response: 'BrainResponse | None' = None,
    ) -> tuple[FreshnessInfo, ...]:
        """
        Compute freshness for time-sensitive domains.
        
        Uses existing timestamps from goal results and task completion.
        Does NOT create new caching system.
        """
        freshness_infos = []
        
        # Domain freshness configs (max age for "fresh" status)
        freshness_config = {
            "weather": 1800,      # 30 minutes
            "finance": 300,       # 5 minutes
            "currency": 300,      # 5 minutes
            "exchange": 300,      # 5 minutes
            "news": 3600,         # 1 hour
            "search": 1800,       # 30 minutes
            "web": 1800,          # 30 minutes
        }
        
        activity = candidate.metadata.get("activity", {})
        active_domains = activity.get("active_domains", [])
        
        # Check brain response for actual completion times
        completion_times = {}
        if brain_response:
            for result in brain_response.results:
                if result.succeeded and result.task_id:
                    # We'd need task completion time - use current time as approximation
                    domain, _, _ = self._infer_context_from_capability(result.capability_id, None)
                    if domain not in completion_times:
                        completion_times[domain] = datetime.now(UTC)
        
        # Also check task manager for completed task times
        tasks = self._task_manager.get_all()
        for task in tasks.values():
            if task.status.name == "COMPLETED" and task.completed_at:
                domain, _, _ = self._infer_context_from_capability(task.request.capability_id, None)
                if domain not in completion_times or task.completed_at > completion_times[domain]:
                    completion_times[domain] = task.completed_at
        
        now = datetime.now(UTC)
        
        for domain_info in active_domains:
            domain_name = domain_info.get("context", "")
            if not domain_name:
                continue
            
            max_age = freshness_config.get(domain_name)
            last_updated = completion_times.get(domain_name)
            
            if last_updated is None:
                status = "unavailable"
            elif max_age is None:
                status = "fresh"  # No freshness requirement
            else:
                age_seconds = (now - last_updated).total_seconds()
                if age_seconds <= max_age:
                    status = "fresh"
                elif age_seconds <= max_age * 4:
                    status = "recent"
                else:
                    status = "stale"
            
            freshness_infos.append(FreshnessInfo(
                domain=domain_name,
                last_updated=last_updated,
                status=status,
                max_age_seconds=float(max_age) if max_age else None,
            ))
        
        return tuple(freshness_infos)
    
    def _enhance_domains_with_phase2(
        self,
        domains: tuple[DomainInfo, ...],
        candidate: _ContextCandidate,
        entities: tuple[EntityInfo, ...],
        topics: tuple[TopicInfo, ...],
        freshness_infos: tuple[FreshnessInfo, ...],
        semantic_relevance: tuple[SemanticRelevance, ...],
    ) -> tuple[DomainInfo, ...]:
        """Enhance existing domains with Phase 2 information."""
        enhanced = []
        
        # Create lookup maps
        entities_by_domain = {}
        for entity in entities:
            if entity.domain not in entities_by_domain:
                entities_by_domain[entity.domain] = []
            entities_by_domain[entity.domain].append(entity)
        
        topics_by_domain = {}
        for topic in topics:
            if topic.domain not in topics_by_domain:
                topics_by_domain[topic.domain] = []
            topics_by_domain[topic.domain].append(topic)
        
        freshness_by_domain = {f.domain: f for f in freshness_infos}
        relevance_by_domain = {r.domain: r.score for r in semantic_relevance}
        
        for domain in domains:
            # Determine contextual role based on relevance and status
            relevance_score = relevance_by_domain.get(domain.name, domain.relevance)
            
            if domain.name == candidate.context:
                contextual_role = ContextualRole.PRIMARY
            elif relevance_score > 0.5:
                contextual_role = ContextualRole.SECONDARY
            else:
                contextual_role = ContextualRole.AMBIENT
            
            # Update domain with Phase 2 info
            enhanced_domain = DomainInfo(
                name=domain.name,
                focus=domain.focus,
                importance=domain.importance,
                status=domain.status,
                capability_ids=domain.capability_ids,
                contextual_role=contextual_role,
                relevance=relevance_score,
                entities=tuple(entities_by_domain.get(domain.name, [])),
                topics=tuple(topics_by_domain.get(domain.name, [])),
                freshness=freshness_by_domain.get(domain.name),
                # Preserve Phase 3 fields
                domain_category=domain.domain_category,
                primary_entities=domain.primary_entities,
                primary_topics=domain.primary_topics,
            )
            enhanced.append(enhanced_domain)
        
        return tuple(enhanced)
    
    def _enhance_surfaces_with_phase2(
        self,
        surfaces: tuple[SurfaceItem, ...],
        candidate: _ContextCandidate,
        freshness_infos: tuple[FreshnessInfo, ...],
        semantic_relevance: tuple[SemanticRelevance, ...],
        brain_response: 'BrainResponse | None' = None,
    ) -> tuple[SurfaceItem, ...]:
        """Enhance existing surfaces with Phase 2 information."""
        enhanced = []
        
        freshness_by_domain = {f.domain: f for f in freshness_infos}
        relevance_by_domain = {r.domain: r.score for r in semantic_relevance}
        
        for surface in surfaces:
            # Determine domain for this surface
            domain, _, _ = self._infer_context_from_capability(surface.capability_id, None)
            
            # Determine contextual role
            domain_relevance = relevance_by_domain.get(domain, 1.0)
            if surface.tier == SurfaceTier.PRIMARY and domain == candidate.context:
                contextual_role = ContextualRole.PRIMARY
            elif surface.tier == SurfaceTier.PRIMARY:
                contextual_role = ContextualRole.SECONDARY
            else:
                contextual_role = ContextualRole.AMBIENT
            
            # Get freshness for this surface's domain
            freshness = freshness_by_domain.get(domain)
            
            enhanced_surface = SurfaceItem(
                capability_id=surface.capability_id,
                label=surface.label,
                tier=surface.tier,
                contextual_role=contextual_role,
                relevance=domain_relevance,
                freshness=freshness,
                metadata=surface.metadata,
                # Preserve Phase 3 fields
                domain=surface.domain,
                semantic_type=surface.semantic_type,
                capability_category=surface.capability_category,
                capability_tags=surface.capability_tags,
            )
            enhanced.append(enhanced_surface)
        
        return tuple(enhanced)
    
    def _enhance_synthesis_with_phase2(
        self,
        synthesis: SynthesisInfo | None,
        candidate: _ContextCandidate,
    ) -> SynthesisInfo | None:
        """Enhance synthesis with Phase 2 contextual role."""
        if synthesis is None:
            return None
        
        # Synthesis is typically PRIMARY when active, SECONDARY when waiting, AMBIENT when completed
        if synthesis.status in ("running", "waiting"):
            contextual_role = ContextualRole.PRIMARY
        elif synthesis.status == "completed":
            contextual_role = ContextualRole.SECONDARY
        else:
            contextual_role = ContextualRole.AMBIENT
        
        return SynthesisInfo(
            goal_id=synthesis.goal_id,
            capability_id=synthesis.capability_id,
            status=synthesis.status,
            depends_on=synthesis.depends_on,
            completed_dependencies=synthesis.completed_dependencies,
            failed_dependencies=synthesis.failed_dependencies,
            contextual_role=contextual_role,
            # Preserve Phase 3 fields
            domain=synthesis.domain,
            semantic_type=synthesis.semantic_type,
            dependency_domains=synthesis.dependency_domains,
        )
    
    def _enhance_dependencies_with_phase2(
        self,
        dependencies: tuple[DependencyInfo, ...],
        candidate: _ContextCandidate,
    ) -> tuple[DependencyInfo, ...]:
        """Enhance dependencies with Phase 2 contextual role."""
        enhanced = []
        
        for dep in dependencies:
            # Determine contextual role based on status and synthesis
            if dep.is_synthesis:
                contextual_role = ContextualRole.PRIMARY
            elif dep.status in ("running", "waiting"):
                contextual_role = ContextualRole.SECONDARY
            elif dep.status == "completed":
                contextual_role = ContextualRole.SECONDARY
            elif dep.status == "failed":
                contextual_role = ContextualRole.PRIMARY  # Failed deps need attention
            else:
                contextual_role = ContextualRole.AMBIENT
            
            enhanced_dep = DependencyInfo(
                goal_id=dep.goal_id,
                capability_id=dep.capability_id,
                depends_on=dep.depends_on,
                status=dep.status,
                is_synthesis=dep.is_synthesis,
                contextual_role=contextual_role,
                # Preserve Phase 3 fields
                domain=dep.domain,
                semantic_type=dep.semantic_type,
                capability_category=dep.capability_category,
                capability_tags=dep.capability_tags,
                dependency_domains=dep.dependency_domains,
            )
            enhanced.append(enhanced_dep)
        
        return tuple(enhanced)
    
    def get_current_state(self) -> UIContextState:
        """
        Get the current semantic UI context state.
        
        Returns:
            Current immutable UIContextState snapshot.
            
        Raises:
            UIContextNotReadyError: If projector is not initialized.
        """
        if self._shutdown:
            raise UIContextNotReadyError("Projector has been shut down")
        
        with self._lock:
            if self._current_state is None:
                raise UIContextNotReadyError("Projector not initialized")
            return self._current_state
    
    def is_ready(self) -> bool:
        """Check if projector is ready to serve requests."""
        return not self._shutdown and self._current_state is not None