"""
PARIKA UI Context Projector.

Derives semantic UI context from Core signals.
Subscribes to EventBus events, reads state, and maintains an immutable snapshot.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

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
    FocusArea,
    SurfaceItem,
    SurfaceTier,
    UIContextState,
    UrgencyLevel,
)


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
        "task.created",
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
        """
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)
        self._task_manager = task_manager
        self._workflow_engine = workflow_engine
        self._context_manager = context_manager
        self._state_manager = state_manager
        self._capability_registry = capability_registry
        
        self._lock = threading.RLock()
        self._current_state: UIContextState | None = None
        self._version = 0
        self._subscribed = False
        self._shutdown = False
        
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
    
    def _on_core_event(self, payload: Any) -> None:
        """Handle Core events that may affect semantic UI state."""
        if self._shutdown:
            return
        
        try:
            self._recompute_and_publish()
        except Exception:
            self._logger.exception("Error recomputing UI context from event")
    
    def _recompute_and_publish(self) -> None:
        """Recompute semantic state and publish if changed."""
        new_state = self._compute_semantic_state()
        
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
            
            # Create new state with incremented version
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
            )
            
            changed_fields = self._compute_changed_fields(self._current_state, changed_state)
            source_event = getattr(new_state, '_source_event', None)
            
            self._current_state = changed_state
            self._publish_change(changed_state, previous_version, changed_fields, source_event)
    
    def _is_semantic_noop(self, old_state: UIContextState, new_state: UIContextState) -> bool:
        """Check if two states are semantically identical (no-op)."""
        return (
            old_state.context == new_state.context and
            old_state.confidence == new_state.confidence and
            old_state.source == new_state.source and
            old_state.attention == new_state.attention and
            old_state.urgency == new_state.urgency and
            old_state.focus == new_state.focus and
            self._surfaces_equal(old_state.surfaces, new_state.surfaces)
        )
    
    def _surfaces_equal(self, old: tuple[SurfaceItem, ...], new: tuple[SurfaceItem, ...]) -> bool:
        """Check if surface tuples are semantically equal."""
        if len(old) != len(new):
            return False
        for o, n in zip(old, new):
            if o.capability_id != n.capability_id or o.label != n.label or o.tier != n.tier:
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
    
    def _compute_semantic_state(self) -> UIContextState:
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
            return self._build_state_from_candidate(task_candidate)
        
        # Try to resolve from active workflow
        workflow_candidate = self._resolve_from_active_workflow()
        if workflow_candidate is not None:
            return self._build_state_from_candidate(workflow_candidate)
        
        # Try to resolve from ContextManager
        context_candidate = self._resolve_from_context_manager()
        if context_candidate is not None:
            return self._build_state_from_candidate(context_candidate)
        
        # Try to resolve from interaction state
        interaction_candidate = self._resolve_from_interaction_state()
        if interaction_candidate is not None:
            return self._build_state_from_candidate(interaction_candidate)
        
        # Fallback
        return self._build_fallback_state()
    
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
        
        # Classify tasks by capability type
        semantic_tasks = []
        transport_tasks = []
        
        for task in all_candidate_tasks:
            capability_id = task.request.capability_id
            capability_def = self._capability_registry.get(capability_id) if self._capability_registry.contains(capability_id) else None
            
            if _is_semantic_capability(capability_id, capability_def):
                semantic_tasks.append((task, capability_id, capability_def))
            else:
                transport_tasks.append((task, capability_id, capability_def))
        
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
        
        # Build surfaces from related capabilities
        surfaces = self._build_surfaces_for_context(context)
        
        # Determine attention from task status
        attention = self._attention_from_task_status(primary_task.status.name)
        
        # Determine urgency - check for critical system events
        urgency = self._determine_urgency()
        
        metadata = MappingProxyType({
            "task_id": primary_task.id,
            "capability_id": capability_id,
            "task_status": primary_task.status.name,
        })
        
        return _ContextCandidate(
            context=context,
            confidence=confidence,
            source=ContextSource.TASK,
            focus=focus,
            surfaces=surfaces,
            metadata=metadata,
            attention=attention,
            urgency=urgency,
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
        return UIContextState(
            version=self._version + 1,
            context="system",
            confidence=0.3,
            source=ContextSource.FALLBACK,
            attention=AttentionLevel.AMBIENT,
            urgency=self._determine_urgency(),
            focus=FocusArea.GENERAL,
            surfaces=self._build_surfaces_for_context("system"),
            timestamp=datetime.now(UTC),
            metadata=MappingProxyType({}),
        )
    
    def _build_state_from_candidate(self, candidate: _ContextCandidate) -> UIContextState:
        """Build UIContextState from a resolved candidate."""
        return UIContextState(
            version=self._version + 1,
            context=candidate.context,
            confidence=candidate.confidence,
            source=candidate.source,
            attention=candidate.attention,
            urgency=candidate.urgency,
            focus=candidate.focus,
            surfaces=candidate.surfaces,
            timestamp=datetime.now(UTC),
            metadata=candidate.metadata,
        )
    
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
    
    def _build_surfaces_for_context(self, context: str) -> tuple[SurfaceItem, ...]:
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
                surfaces.append(SurfaceItem(
                    capability_id=cap_id,
                    label=label,
                    tier=tier,
                    metadata=MappingProxyType({}),
                ))
        
        # Always add ambient system surfaces
        for cap_id, label, tier in context_surfaces["system"]:
            if self._capability_registry.contains(cap_id):
                # Avoid duplicates
                if not any(s.capability_id == cap_id for s in surfaces):
                    surfaces.append(SurfaceItem(
                        capability_id=cap_id,
                        label=label,
                        tier=tier,
                        metadata=MappingProxyType({}),
                    ))
        
        return tuple(surfaces)
    
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