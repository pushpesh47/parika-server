"""
PARIKA Interfaces - Session

Defines `InterfaceSession`, the reusable session-lifecycle and
request-construction abstraction shared by every Interface.

`InterfaceSession` owns:

- Session lifecycle (identity, start time, conversation history).
- Request parsing: turning free text into a `BrainRequest` via
  `chat_capability.build_chat_goal()`.
- Submitting that request to Brain and interpreting the resulting
  `BrainResponse`/`GoalResult` into a small `ChatTurnResult` value
  object.

It contains no output formatting or rendering; that is owned by
`parika.interfaces.formatting` and by each concrete Interface (e.g.
the CLI's terminal renderer). It also contains no business logic:
capability resolution, policy evaluation, provider/tool selection, and
execution all remain owned by Brain, Planner, and the rest of Core,
exactly as for any other Goal.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from parika.core.brain.brain_request import BrainRequest
from parika.core.brain.brain_response import BrainResponse, RequestStatus
from parika.core.brain.context_engine import ContextBundle, load_context_engine_config
from parika.core.planner.goal import (
    Goal,
    ROUTING_GOAL_METADATA_KEY,
    TERMINAL_SYNTHESIS_GOAL_METADATA_KEY,
)
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.provider_manager.tool_spec import ToolSpec
from parika.core.utilities.progress import ProgressEvent, ProgressStage

from .chat_capability import (
    assemble_context_messages,
    assemble_conversation_messages,
    assemble_session_retrieval_messages,
    build_assistant_system_prompt,
    build_chat_goal,
    decompose_and_build_goals,
    discover_tool_specs,
)
from .ai_context.goal_decomposer import (
    DecompositionError,
    DecompositionResult
)
from .ai_context.admission import (
    ExecutionModeAdmission,
    create_execution_mode_admission,
)
from .ai_context.goal_decomposer import ExecutionMode
from parika.core.autonomous.execution_mode import (
    AdmissionDecision,
    AdmissionState,
)
from parika.core.autonomous.contracts import AutonomousTaskStatus
from parika.core.forensic_log import (
    set_trace_context,
    get_current_trace_id,
    log_final_result,
)
from .conversation_state import ConversationState, ConversationStateManager, build_static_prefix
from .history import HistoryEntry, HistoryRole
from .runtime import ParikaRuntime
from .postgresql_session_store import PostgreSQLSessionStore, SessionNotFoundError


@dataclass(frozen=True, slots=True, kw_only=True)
class LastTurnDiagnostics:
    """
    Immutable snapshot of runtime-intelligence diagnostics for the
    most recently submitted chat turn, displayed by the CLI's
    `/status` command (Phase 1 Completion Specification section 18).
    """

    conversation_message_count: int = 0
    conversation_tokens: int = 0
    memory_hits: int = 0
    knowledge_hits: int = 0
    experience_success_rate: float | None = None
    context_tokens: int = 0
    advertised_tools: tuple[str, ...] = ()
    selected_provider: str | None = None
    selected_model: str | None = None
    progress_trail: tuple[ProgressEvent, ...] = ()
    """
    Every `ProgressEvent` published on the generic `progress.*`
    channels while this turn was being submitted (Phase 3.5b) --
    `memory.search`, `knowledge.search`, and Brain's own
    `brain.execution` tree, in publication order. Captured purely for
    post-hoc/late diagnostics (e.g. a late `/status` inspection); the
    live, real-time signal remains the `EventBus` publication itself,
    which any subscriber (e.g. the Console) observes as it happens.
    Empty when nothing was published (e.g. `Brain` was constructed
    without an `event_bus`).
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatTurnResult:
    """
    Immutable outcome of submitting one chat turn to Brain.
    """

    brain_response: BrainResponse
    """
    Raw BrainResponse produced for this turn.
    """

    @property
    def succeeded(self) -> bool:
        """
        Whether the turn completed successfully.

        For multi-goal requests with a synthesis goal (chat.respond), the turn
        is considered successful if the synthesis goal produced a response,
        even if some independent data-gathering goals failed. This ensures
        the user receives the generated response with acknowledgment of any
        failures.

        For single-goal requests and planning failures, falls back to the
        BrainResponse's overall success status.
        """

        # If there's a chat response, the synthesis succeeded and user gets a response
        if self.chat_response is not None:
            return True

        # Otherwise fall back to brain response success (planning failure or all goals failed)
        return self.brain_response.succeeded

    @property
    def status(self) -> RequestStatus:
        """
        Three-state status of this turn.
        
        Delegates to BrainResponse.status for the authoritative status.
        """
        return self.brain_response.status

    @property
    def partial_success(self) -> bool:
        """
        Whether this turn achieved partial success.
        
        Delegates to BrainResponse.partial_success.
        """
        return self.brain_response.partial_success

    @property
    def chat_response(self) -> ChatResult | None:
        """
        The provider-independent `ChatResult` produced for this turn,
        if any. Every Provider's driver is responsible for returning
        one whenever it executes a `ChatRequest` (see
        `parika.core.provider_manager.chat_request.ChatRequest`) --
        this property never needs to know which concrete Provider
        actually ran.
        """

        if not self.brain_response.results:
            return None

        # Find the goal result that contains a ChatResult (typically the final synthesis goal)
        for goal_result in self.brain_response.results:
            if goal_result.response is None:
                continue
            backend_response = goal_result.response.outputs.get("result")
            if isinstance(backend_response, ChatResult):
                return backend_response

        return None

    @property
    def error_message(self) -> str | None:
        """
        Human-readable description of why the turn did not succeed,
        or None if it succeeded.
        """

        if self.brain_response.planning_failure is not None:
            return str(self.brain_response.planning_failure)

        if not self.brain_response.results:
            return None

        # Check all goal results for errors
        for goal_result in self.brain_response.results:
            if goal_result.skipped:
                return goal_result.skip_reason
            if goal_result.failure is not None:
                return str(goal_result.failure)

        return None


def _estimate_conversation_tokens(messages: "tuple[ChatMessage, ...] | list[ChatMessage]") -> int:
    """
    Same coarse `len(text) // 4` heuristic as
    `context_engine.HeuristicTokenEstimator`, applied to the rolling
    conversation history for `/status`'s "Conversation tokens"
    diagnostic. Deliberately not importing Brain's private
    context_engine class here -- this is Interfaces-layer
    introspection, not Context Assembly itself.
    """

    total_characters = sum(len(message.content) for message in messages)

    return max(0, total_characters // 4)


def _build_last_turn_diagnostics(
    *,
    context_bundle: ContextBundle | None,
    advertised_tools: tuple[ToolSpec, ...],
    brain_response: BrainResponse,
    conversation_tokens: int,
    progress_trail: tuple[ProgressEvent, ...] = (),
) -> LastTurnDiagnostics:
    """
    Build a `LastTurnDiagnostics` snapshot from this turn's
    `ContextBundle` and `BrainResponse`. `selected_provider`/
    `selected_model` are read from `TaskResponse.metadata`, populated
    by `CapabilityExecutor` only for provider-backed capabilities (see
    Phase 1 Completion Specification section 18).
    """

    selected_provider: str | None = None
    selected_model: str | None = None

    if brain_response.results:
        response = brain_response.results[0].response

        if response is not None:
            selected_provider = response.metadata.get("provider_id")
            selected_model = response.metadata.get("model_id")

    return LastTurnDiagnostics(
        conversation_message_count=(
            context_bundle.conversation_message_count if context_bundle is not None else 0
        ),
        conversation_tokens=conversation_tokens,
        memory_hits=len(context_bundle.memories) if context_bundle is not None else 0,
        knowledge_hits=len(context_bundle.knowledge) if context_bundle is not None else 0,
        experience_success_rate=(
            context_bundle.experience_success_rate if context_bundle is not None else None
        ),
        context_tokens=context_bundle.estimated_tokens if context_bundle is not None else 0,
        advertised_tools=tuple(spec.name for spec in advertised_tools),
        selected_provider=selected_provider,
        selected_model=selected_model,
        progress_trail=progress_trail,
    )


class _SystemPromptNotProvided:
    """
    Private sentinel type used only as `InterfaceSession.__init__()`'s
    `system_prompt` default value.

    Distinguishes "the caller omitted `system_prompt` entirely" (this
    sentinel) from an explicitly passed `system_prompt=None`, which
    must continue to mean "seed no system prompt at all" -- existing,
    test-verified behavior that predates Assistant Identity (see
    `tests/interfaces/test_session.py` and
    `tests/interfaces/test_session_persistence.py`). Using `None`
    itself as the default would make these two cases
    indistinguishable and silently change that existing contract.
    """


_SYSTEM_PROMPT_NOT_PROVIDED = _SystemPromptNotProvided()


class InterfaceSession:
    """
    A single interactive session against a `ParikaRuntime`.

    Maintains conversation state via explicit `ConversationState`
    (which separates static prefix from dynamic history) and a
    separate, display-oriented `HistoryEntry` log used by slash
    commands such as `/history`.
    """

    def __init__(
        self,
        runtime: ParikaRuntime,
        *,
        session_id: str | None = None,
        system_prompt: (
            str | None | _SystemPromptNotProvided
        ) = _SYSTEM_PROMPT_NOT_PROVIDED,
        session_store: PostgreSQLSessionStore | None = None,
    ) -> None:
        """
        Initialize the session.

        Args:
            runtime:
                Runtime this session submits requests through.

            session_id:
                Optional explicit session identifier. A random one is
                generated when omitted.

            system_prompt:
                Optional system prompt seeded as the first chat
                message. Omit this argument entirely to seed PARIKA's
                default Assistant Identity prompt, built from
                `runtime.configuration`'s `[assistant]` section (see
                `chat_capability.build_assistant_system_prompt()`).
                Pass an explicit string to seed that text instead.
                Pass `None` explicitly to start with no system prompt
                at all -- unchanged, pre-existing behavior.

            session_store:
                Optional SqliteSessionStore. Defaults to None, in which
                case this session behaves exactly as before this
                milestone (purely in-memory, no persistence). When
                supplied, every turn is additionally persisted, and
                `save()`/`load()`/`list_sessions()` become usable. See
                docs/architecture/Intelligence_Foundation_Design.md
                section 8.
        """

        self._runtime = runtime
        self._state_manager = ConversationStateManager(session_store)
        self._logger = runtime.logger.get_logger(__name__)
        
        resolved_system_prompt = (
            build_assistant_system_prompt(runtime.configuration)
            if isinstance(system_prompt, _SystemPromptNotProvided)
            else system_prompt
        )

        self._conversation_state = self._state_manager.create_initial_state(
            runtime,
            session_id=session_id,
            system_prompt=None if isinstance(system_prompt, _SystemPromptNotProvided) else system_prompt,
        )
        
        self._history: list[HistoryEntry] = []
        self._last_turn_diagnostics: LastTurnDiagnostics | None = None

    @property
    def runtime(self) -> ParikaRuntime:
        """
        The runtime this session is bound to.
        """

        return self._runtime

    @property
    def id(self) -> str:
        """Conversation identifier."""
        return self._conversation_state.id

    @property
    def started_at(self) -> datetime:
        """Conversation start timestamp."""
        return self._conversation_state.started_at

    @property
    def session_store(self) -> PostgreSQLSessionStore | None:
        """
        The PostgreSQLSessionStore this session persists through, or None
        if this session is purely in-memory (the default).
        """

        return self._state_manager._session_store

    @property
    def last_turn_diagnostics(self) -> LastTurnDiagnostics | None:
        """
        Runtime-intelligence diagnostics for the most recently
        submitted chat turn, or None before any turn has been
        submitted. See `/status`'s use of this in
        `commands/builtin.py`.
        """

        return self._last_turn_diagnostics

    def history(self) -> tuple[HistoryEntry, ...]:
        """
        Return every recorded history entry, oldest first.
        """

        return tuple(self._history)

    def record(self, role: HistoryRole, text: str) -> None:
        """
        Record a display-oriented history entry.

        Used by slash-command handlers to log their own invocations
        without going through `submit_text()`.
        """

        self._history.append(HistoryEntry(role=role, text=text))

    def clear(self) -> None:
        """
        Clear conversation and display history.

        Any system prompt seeded at construction time is preserved so
        the model's behavior remains consistent after clearing.
        """

        self._conversation_state = self._conversation_state.clear_history()
        self._history.clear()

    def submit_text(
        self,
        text: str,
        *,
        on_token: Callable[[str], None] | None = None,
    ) -> ChatTurnResult:
        """
        Submit free text as one chat turn.

        Builds a `BrainRequest` targeting the `chat.respond`
        Capability and hands it to `Brain.handle()`. On success, the
        model's reply is appended to the rolling conversation history
        so subsequent turns retain context.

        Args:
            text:
                User-authored message text.

            on_token:
                Optional callback invoked with each streamed content
                fragment of the model's final answer.

        Returns:
            The outcome of this turn.
        """

        # FORENSIC: Set trace context for this request
        trace_id = set_trace_context(user_query=text, session_id=self.id)
        
        user_message = ChatMessage(role="user", content=text)
        self._history.append(HistoryEntry(role=HistoryRole.USER, text=text))
        self._conversation_state = self._conversation_state.append_user_message(user_message)

        # Automatically generate and persist title on first user message if not already set
        if self._state_manager._session_store is not None:
            self._state_manager._session_store.append_message(self.id, role="user", content=text)
            
            # Check if this is the first user message and title is not set
            existing = self._state_manager._session_store.get_session(self.id)
            if existing is not None and existing.title is None:
                # This is the first user message - generate title from it
                title = text.strip().splitlines()[0][:80]
                if title:  # Only set if non-empty after stripping
                    self._state_manager._session_store.set_title(self.id, title)

        # Execution progress diagnostics (Phase 3.5b): temporarily
        # subscribe to the generic progress.* channels for the
        # duration of this turn so LastTurnDiagnostics.progress_trail
        # can offer a post-hoc replay (e.g. a late `/status`
        # inspection). This never affects live delivery -- any
        # subscriber already watching the EventBus (e.g. the Console)
        # observes each ProgressEvent as it happens, independent of
        # this collection. See `memory.search`/`knowledge.search`
        # (self-reported by MemoryManager/KnowledgeManager) and
        # Brain's own `brain.execution` tree.
        progress_trail: list[ProgressEvent] = []

        def _collect_progress(event: object) -> None:
            if isinstance(event, ProgressEvent):
                progress_trail.append(event)

        for stage in ProgressStage:
            self._runtime.event_bus.subscribe(
                f"progress.{stage.value}", _collect_progress
            )

        try:
            return self._submit_text(text, on_token=on_token, progress_trail=progress_trail)

        finally:
            for stage in ProgressStage:
                self._runtime.event_bus.unsubscribe(
                    f"progress.{stage.value}", _collect_progress
                )

    def _submit_text(
        self,
        text: str,
        *,
        on_token: Callable[[str], None] | None,
        progress_trail: list[ProgressEvent],
    ) -> ChatTurnResult:
        # NEW: Try multi-goal decomposition first
        # This will return multiple goals for complex requests,
        # or a single chat.respond goal for simple requests
        try:
            decomposition_result = decompose_and_build_goals(
                latest_message=text,
                runtime=self._runtime,
            )
            goals = decomposition_result.goals
            # Track the provider/model that successfully completed decomposition
            preferred_synthesis_provider_id = decomposition_result.successful_provider_id
            preferred_synthesis_model_id = decomposition_result.successful_model_id
            
            # ADMISSION: Determine execution mode
            admission = create_execution_mode_admission(
                runtime=self._runtime,
                session=self,
            )
            admission_decision = admission.resolve(
                proposed_semantic_mode=decomposition_result.proposed_semantic_mode,
                confidence=decomposition_result.execution_mode_confidence,
                reasons=decomposition_result.execution_mode_reasons,
                goals=decomposition_result.goals,
            )
            
            # If admitted to autonomous, use autonomous mission bridge
            if admission_decision.admitted_mode is ExecutionMode.AUTONOMOUS:
                return self._submit_autonomous(
                    text=text,
                    decomposition_result=decomposition_result,
                    admission_decision=admission_decision,
                    on_token=on_token,
                    progress_trail=progress_trail,
                )
            # If admitted to normal, continue with normal execution below
            
        except DecompositionError as ex:
            # Decomposition failed - return a failed ChatTurnResult
            self._logger.warning(f"Goal decomposition failed: {ex}")
            
            # Create a minimal failed response
            from parika.core.brain.brain_response import BrainResponse, RequestStatus
            from parika.core.brain.goal_result import GoalResult
            
            brain_response = BrainResponse(
                request_id=uuid4().hex,
                plan_id=None,
                results=(
                    GoalResult(
                        goal_id="decomposition_failed",
                        capability_id="chat.respond",
                        task_id=None,
                        status=None,
                        failure=ex,
                    ),
                ),
                planning_failure=ex,
            )
            
            return ChatTurnResult(brain_response=brain_response)

        # For goals that need context assembly (primarily chat.respond for final synthesis),
        # we still need to assemble context and inject it into the conversation
        # But we do this per-goal rather than once for the whole request
        
        # First, check if any goal is chat.respond (final synthesis)
        chat_respond_goals = [g for g in goals if g.capability_id == "chat.respond"]
        other_goals = [g for g in goals if g.capability_id != "chat.respond"]

        # If we have chat.respond goals, they need the full conversation context
        # For other goals (tools), they typically don't need conversation history
        # but may need memory/knowledge context if their inputs reference it
        
        # Assemble context once for the whole turn (for chat.respond)
        # Tool goals will get their context from their own inputs
        context_messages, context_bundle = assemble_context_messages(
            self._runtime,
            text=text,
            session_id=self.id,
            conversation_message_count=len(self._conversation_state.full_history),
        )

        session_token_budget = load_context_engine_config(
            self._runtime.configuration
        ).usable_tokens
        already_used_tokens = (
            context_bundle.estimated_tokens if context_bundle is not None else 0
        )

        session_messages = assemble_session_retrieval_messages(
            text=text,
            session_store=self._state_manager._session_store,
            current_session_id=self.id,
            token_budget=max(0, session_token_budget - already_used_tokens),
        )

        injected_messages = context_messages + session_messages

        # For chat.respond goals, inject context into their inputs
        effective_messages = assemble_conversation_messages(
            self._conversation_state.full_history, injected_messages
        )

        # Build tools for the routing model (chat.respond) if needed
        tools = discover_tool_specs(self._runtime, text=text)

        # Identify the terminal synthesis goal: the chat.respond goal that
        # has dependencies (complex request) or the sole chat.respond goal
        # (simple request). This is the final response generation step.
        chat_respond_goals = [g for g in goals if g.capability_id == "chat.respond"]
        synthesis_goal_id: str | None = None
        if chat_respond_goals:
            # Per decomposition contract: exactly one chat.respond goal has
            # dependencies (the synthesis goal), or there's only one total.
            synthesis_candidates = [g for g in chat_respond_goals if g.depends_on]
            if synthesis_candidates:
                synthesis_goal_id = synthesis_candidates[0].id
            elif len(chat_respond_goals) == 1:
                synthesis_goal_id = chat_respond_goals[0].id

        # Enhance chat.respond goals with context and tools
        enhanced_goals = []
        for goal in goals:
            if goal.capability_id == "chat.respond":
                # For synthesis goals (those with dependencies), don't pass tools
                # The dependency results are injected via system message by Brain
                goal_tools = () if goal.depends_on else tools

                # Rebuild this goal with proper context and tools
                enhanced_goal = build_chat_goal(
                    messages=effective_messages,
                    tools=goal_tools,
                    on_token=on_token,
                    latest_message=text,
                    runtime=self._runtime,
                )
                # Build metadata: start with enhanced goal's metadata (includes
                # ROUTING_GOAL_METADATA_KEY), then add terminal synthesis marker
                # for the synthesis goal so fixed routing model also applies here.
                metadata = dict(enhanced_goal.metadata)
                if goal.id == synthesis_goal_id:
                    metadata[TERMINAL_SYNTHESIS_GOAL_METADATA_KEY] = True
                    # Carry forward the provider/model that successfully completed
                    # goal decomposition, so synthesis tries it first.
                    if preferred_synthesis_provider_id is not None:
                        metadata["preferred_synthesis_provider_id"] = preferred_synthesis_provider_id
                    if preferred_synthesis_model_id is not None:
                        metadata["preferred_synthesis_model_id"] = preferred_synthesis_model_id

                # Preserve original goal metadata (dependencies, etc.) and merge
                # with our additions
                metadata.update(goal.metadata)

                enhanced_goal = Goal(
                    id=goal.id,
                    capability_id=goal.capability_id,
                    inputs=goal.inputs,  # Keep original inputs (message to summarize)
                    depends_on=goal.depends_on,
                    provider_request_builder=enhanced_goal.provider_request_builder,
                    metadata=metadata,
                )
                enhanced_goals.append(enhanced_goal)
            else:
                # Tool goals keep their decomposed inputs
                enhanced_goals.append(goal)

        # Execute ALL goals through Brain
        brain_response = self._runtime.brain.handle(
            BrainRequest(goals=tuple(enhanced_goals))
        )

        result = ChatTurnResult(brain_response=brain_response)

        # FORENSIC: Log final result
        trace_id = get_current_trace_id()
        if trace_id:
            used_tools = []
            for goal_result in brain_response.results:
                if goal_result.succeeded and goal_result.capability_id not in ["chat.respond"]:
                    used_tools.append(goal_result.capability_id)
            
            final_response = result.chat_response.message.content if result.chat_response else (result.error_message or "")
            log_final_result(
                trace_id=trace_id,
                success=result.succeeded,
                used_tools=used_tools,
                response=final_response,
                response_status=result.status.value,
                request_id=brain_response.request_id,
)
        
        self._last_turn_diagnostics = _build_last_turn_diagnostics(
            context_bundle=context_bundle,
            advertised_tools=tools,
            brain_response=brain_response,
            conversation_tokens=_estimate_conversation_tokens(self._conversation_state.full_history),
            progress_trail=tuple(progress_trail),
        )
        
        if result.succeeded and result.chat_response is not None:
            assistant_message = result.chat_response.message
            self._conversation_state = self._conversation_state.append_assistant_message(assistant_message)
            self._history.append(
                HistoryEntry(
                    role=HistoryRole.ASSISTANT,
                    text=result.chat_response.message.content,
                )
            )

            if self._state_manager._session_store is not None:
                self._state_manager._session_store.append_message(
                    self.id, role="assistant", content=result.chat_response.message.content
                )
        else:
            error_text = result.error_message or "The request failed."

            self._history.append(
                HistoryEntry(role=HistoryRole.ERROR, text=error_text)
            )

            if self._state_manager._session_store is not None:
                self._state_manager._session_store.append_message(self.id, role="error", content=error_text)

        return result

    def _resolve_dependency_references(
        self,
        inputs: dict[str, Any],
        goal_id_to_task_id: dict[str, str],
        all_goals: list[Goal],
    ) -> dict[str, Any]:
        """
        Resolve dependency references in inputs from {{goal_X.result.field}} syntax to actual values.
        For autonomous missions, we store the mapping and let the runtime resolve actual values
        during task execution.
        """
        import re
        from copy import deepcopy
        
        resolved_inputs = deepcopy(inputs)
        
        # Pattern to match {{goal_id.result.field}} or {{goal_id.result[index]}} or nested paths
        pattern = r'\{\{([a-zA-Z0-9_]+)\.result\.([a-zA-Z0-9_.[\]]+)\}\}'
        
        def resolve_value(obj: Any) -> Any:
            if isinstance(obj, str):
                # Find all dependency references in the string
                matches = re.findall(pattern, obj)
                if matches:
                    # Replace each reference with a placeholder - actual resolution happens at runtime
                    # For now, we keep the reference as-is since the autonomous runtime will handle it
                    pass
                return obj
            elif isinstance(obj, dict):
                return {k: resolve_value(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [resolve_value(item) for item in obj]
            else:
                return obj
        
        # Apply resolution to all input values
        for key, value in resolved_inputs.items():
            resolved_inputs[key] = resolve_value(value)
            
        return resolved_inputs

    def _submit_autonomous(
        self,
        text: str,
        *,
        decomposition_result: DecompositionResult,
        admission_decision: AdmissionDecision,
        on_token: Callable[[str], None] | None,
        progress_trail: list[ProgressEvent],
    ) -> ChatTurnResult:
        """
        Handle autonomous execution mission creation and monitoring.
        
        Creates an autonomous mission from the decomposition result, starts it,
        and returns a ChatTurnResult indicating the mission has been launched.
        The actual mission execution happens in the background via AutonomousRuntime.
        
        NOTE: Terminal chat.respond synthesis is NOT executed as an autonomous task.
        chat.respond is explicitly unsupported for autonomous execution (see provider_factories.py).
        Users must use mission.get_result to retrieve results, followed by a normal
        chat turn for final synthesis if needed.
        """
        from parika.core.autonomous.mission_manager import Mission
        from parika.core.autonomous.contracts import MissionStatus
        
        # Extract goals from decomposition result
        goals = decomposition_result.goals
        
        mission = None
        created_task_ids = []
        mission_id = None
        try:
            # Create the autonomous mission through the mission manager
            mission = self._runtime.autonomous_runtime.mission_manager.create(goal=text)
            mission_id = mission.id
        

            
            # Convert decomposition goals to autonomous tasks with explicit goal_id -> task_id mapping
            goal_id_to_task_id = {}
            autonomous_goals = [g for g in goals if g.capability_id != "chat.respond"]
            
            # First pass: create all non-chat.respond tasks WITHOUT dependencies
            # We'll add dependencies in a second pass once all task IDs are known
            task_creation_data = []
            for goal in autonomous_goals:
                task_inputs = dict(goal.inputs)
                
                # Resolve dependency references ({{goal_X.result.field}} syntax)
                resolved_inputs = self._resolve_dependency_references(
                    task_inputs, goal_id_to_task_id, goals
                )
                
                task_creation_data.append({
                    'goal': goal,
                    'inputs': resolved_inputs,
                })
            
            # Create tasks for non-chat.respond goals
            for data in task_creation_data:
                goal = data['goal']
                resolved_inputs = data['inputs']
                
                # Create the autonomous task
                task = self._runtime.autonomous_runtime.task_manager.create(
                    mission_id=mission_id,
                    name=goal.id,  # Use goal ID as task name for traceability
                    description=f"Execute {goal.capability_id}",
                    capability_id=goal.capability_id,
                    inputs=resolved_inputs,
                )
                
                # Store the mapping for dependency resolution
                goal_id_to_task_id[goal.id] = task.id
                created_task_ids.append(task.id)
            
            # Second pass: add dependencies for non-chat.respond tasks
            # We need to use the TaskDependencyRepository directly since the task
            # manager's create method expects dependencies at creation time
            from parika.core.autonomous.repository import TaskDependencyRepository
            from parika.core.autonomous.models import TaskDependencyModel
            from parika.core.autonomous.contracts import DependencyStatus
            from datetime import datetime, UTC
            
            dep_repo = TaskDependencyRepository(
                self._runtime.autonomous_runtime.sync_pool,
                self._runtime.logger
            )
            
            for data in task_creation_data:
                goal = data['goal']
                task_id = goal_id_to_task_id[goal.id]
                
                if goal.depends_on:
                    dep_task_ids = tuple(goal_id_to_task_id[dep_id] for dep_id in goal.depends_on if dep_id in goal_id_to_task_id)
                    if dep_task_ids:
                        task = self._runtime.autonomous_runtime.task_manager.get(task_id)
                        if task:
                            # Update task status to WAITING_FOR_DEPENDENCY since it has dependencies
                            task.status = AutonomousTaskStatus.WAITING_FOR_DEPENDENCY
                            task.updated_at = datetime.now(UTC)
                            self._runtime.autonomous_runtime.task_manager.update(task)
                            
                            for dep_task_id in dep_task_ids:
                                dep = TaskDependencyModel(
                                    id=f"dep_{task.id}_{dep_task_id}",
                                    task_id=task.id,
                                    depends_on_task_id=dep_task_id,
                                    status=DependencyStatus.WAITING.value,
                                    created_at=datetime.now(UTC),
                                )
                                dep_repo.create(dep)
            
            # NOTE: chat.respond goals are NOT created as autonomous tasks.
            # chat.respond is explicitly unsupported for autonomous execution.
            # The terminal synthesis must happen in a normal chat turn after
            # the user retrieves mission results via mission.get_result.
            
            # Start the mission
            started_mission = self._runtime.autonomous_runtime.mission_manager.start(mission_id)
            if started_mission is None:
                raise RuntimeError(f"Failed to start mission {mission_id}: invalid state transition")
            
            # FORENSIC: Log mission creation
            trace_id = get_current_trace_id()
            if trace_id:
                from parika.core.forensic_log import log_generic
                log_generic(trace_id, "mission.created", {
                    "mission_id": mission_id,
                    "goal": text,
                    "task_count": len(goal_id_to_task_id),
                    "admission_reason": admission_decision.reason
                })
            
            # Return a ChatTurnResult indicating the mission has been launched
            # The actual result will be available via mission.get_result capability
            from parika.core.brain.brain_response import BrainResponse, RequestStatus
            from parika.core.brain.goal_result import GoalResult
            from parika.core.provider_manager.chat_result import ChatResult, ChatMessage
            
            # Create a synthetic chat response indicating mission launched
            launched_message = ChatResult(
                message=ChatMessage(
                    role="assistant",
                    content=f"Autonomous mission '{mission_id[:8]}...' launched successfully with {len(goal_id_to_task_id)} tasks. "
                           f"Use 'mission.get_result' with mission_id='{mission_id}' to check progress and retrieve results."
                )
            )
            
            # Create a synthetic brain response with the launched message
            synthetic_response = BrainResponse(
                request_id=decomposition_result.raw_response or "autonomous_launched",
                plan_id=None,
                results=(
                    GoalResult(
                        goal_id="mission_launched",
                        capability_id="chat.respond",
                        task_id=None,
                        status=RequestStatus.COMPLETED,
                        outputs={"result": launched_message},
                    ),
                ),
            )
            
            chat_result = ChatTurnResult(brain_response=synthetic_response)
            
            # Update last turn diagnostics for autonomous launch
            self._last_turn_diagnostics = _build_last_turn_diagnostics(
                context_bundle=None,  # No context bundle for synthetic response
                advertised_tools=(),
                brain_response=synthetic_response,
                conversation_tokens=0,
                progress_trail=tuple(progress_trail),
            )
            
            # Record in conversation history
            assistant_message = synthetic_response.results[0].response
            if assistant_message:
                self._conversation_state = self._conversation_state.append_assistant_message(assistant_message)
                self._history.append(
                    HistoryEntry(
                        role=HistoryRole.ASSISTANT,
                        text=assistant_message.content,
                    )
                )
                
                if self._state_manager._session_store is not None:
                    self._state_manager._session_store.append_message(
                        self.id, role="assistant", content=assistant_message.content
                    )
            
            return chat_result
            
        except Exception as ex:
            # Handle any failure during mission/task creation
            self._logger.error(f"Autonomous mission creation failed: {ex}", exc_info=True)
            
            # Return an error response
            from parika.core.brain.brain_response import BrainResponse, RequestStatus
            from parika.core.brain.goal_result import GoalResult
            from parika.core.provider_manager.chat_result import ChatResult, ChatMessage
            
            error_message = ChatResult(
                message=ChatMessage(
                    role="assistant",
                    content=f"Autonomous mission creation failed: {str(ex)}"
                )
            )
            
            error_response = BrainResponse(
                request_id=decomposition_result.raw_response or "autonomous_failed",
                plan_id=None,
                results=(
                    GoalResult(
                        goal_id="mission_failed",
                        capability_id="chat.respond",
                        task_id=None,
                        status=RequestStatus.FAILED,
                        outputs={"result": error_message},
                        failure=ex,
                    ),
                ),
            )
            
            chat_result = ChatTurnResult(brain_response=error_response)
            
            # Record in conversation history
            self._history.append(
                HistoryEntry(role=HistoryRole.ERROR, text=f"Autonomous mission creation failed: {str(ex)}")
            )
            
            if self._state_manager._session_store is not None:
                self._state_manager._session_store.append_message(
                    self.id, role="error", content=f"Autonomous mission creation failed: {str(ex)}"
                )
            
            return chat_result

    def save(self) -> None:
        """
        Persist a title (derived deterministically, if not already
        set).

        A no-op if no `session_store` was supplied at construction
        time. Never calls an LLM: title derivation is a simple,
        deterministic truncation of the first user message. Richer
        abstractive summarization (a real `chat.summarize` Goal through
        `Brain.handle()`) is a documented future enhancement, not
        implemented in this milestone -- see
        docs/architecture/Intelligence_Foundation_Design.md section
        8.4.

        Note: Title is now automatically generated on the first user message
        in `submit_text()`. This method exists as a fallback for edge cases.
        """

        if self._state_manager._session_store is None:
            return

        existing = self._state_manager._session_store.get_session(self.id)

        if existing is not None and existing.title is None:
            first_user_entry = next(
                (e for e in self._history if e.role is HistoryRole.USER), None
            )

            if first_user_entry is not None:
                title = first_user_entry.text.strip().splitlines()[0][:80]
                if title:
                    self._state_manager._session_store.set_title(self.id, title)

    @classmethod
    def load(
        cls,
        session_id: str,
        runtime: ParikaRuntime,
        session_store: PostgreSQLSessionStore,
    ) -> "InterfaceSession":
        """
        Restore a previously saved session's messages into a new
        `InterfaceSession`.

        Raises:
            SessionNotFoundError:
                If `session_id` has no stored session.
        """

        if session_store.get_session(session_id) is None:
            raise SessionNotFoundError(f"Session '{session_id}' was not found.")

        session = cls(runtime, session_id=session_id, session_store=session_store)

        # Replace the conversation state with loaded one
        loaded_state = session._state_manager.load_state(
            session_id, runtime, system_prompt=None, agent_context_id=None
        )
        session._conversation_state = loaded_state

        return session

    @staticmethod
    def list_sessions(session_store: PostgreSQLSessionStore) -> tuple[SessionSummary, ...]:
        """Return every stored session's metadata, most recently updated first."""

        return session_store.list_sessions()
