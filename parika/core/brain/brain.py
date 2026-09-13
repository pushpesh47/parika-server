"""
PARIKA Brain

Provides PARIKA's central orchestration engine.

Brain receives a BrainRequest carrying already-decomposed Goal
instances, delegates planning to Planner, supervises execution of the
resulting ExecutionPlan by creating and executing Tasks through
TaskManager, and produces a final BrainResponse summarizing the
outcome of every Goal.

Brain does not replace specialized Core components. It never resolves
capabilities, evaluates policy, selects providers or tools, or
executes capabilities directly; all of that is delegated to Planner,
TaskManager, and CapabilityExecutor. Brain also does not own any
responsibility assigned to another manager; it only coordinates them.

Execution progress reporting
-----------------------------
Brain is the one place every present and future caller of `handle()`
(the native Console today; a Scheduler, WorkflowEngine, or future
Automation caller tomorrow) passes through, regardless of which
Interface or Core component originated the request. Brain therefore
owns the single root of execution progress reporting for its own
orchestration, using the existing, unmodified `EventBus`/
`ProgressReporter` mechanism (`parika/core/utilities/progress.py`) --
never a new event system.

Every `handle()` call publishes one self-contained `brain.execution`
progress tree (`brain.execution.started/progress/completed/failed` on
both the specific `brain.execution.*` channel and the generic
`progress.*` channel -- see `ProgressReporter`), with `brain.planning`
and `brain.execute_goal` children reporting Planner's and each Goal's
Task execution respectively. `brain.execute_goal`'s `task_id` is the
real `TaskManager` `Task.id`, matching `ProgressEvent.task_id`'s
documented meaning; the root has no `task_id`, since one request may
decompose into more than one Task.

Work that happens outside `handle()` (e.g. an Interface's own Memory/
Knowledge context assembly, or response rendering) is not part of
this tree -- it is reported independently, by the component that
performs it, exactly as before; see `docs/architecture/
Core_Component_Responsibilities.md`'s Execution Progress addendum.
Supplying `event_bus` is optional: omitting it (e.g. in isolated unit
tests) leaves every other behavior of `handle()` unchanged and simply
reports no progress.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
import asyncio
import hashlib
import json
import re
import time
from dataclasses import asdict

from parika.core.capability_catalog import CapabilityCatalog
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_resolver import CapabilityResolver
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.permission_manager.workspace_permission_manager import WorkspacePermissionManager
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.policy_engine.policy_effect import PolicyEffect
from parika.core.policy_engine.request import PolicyEvaluationRequest
from parika.core.planner.execution_plan import ExecutionPlan
from parika.core.planner.goal import Goal
from parika.core.planner.plan_step import PlanStep
from parika.core.planner.planner import Planner
from parika.core.provider_manager.chat_request import ChatRequest
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.task_manager.request import TaskRequest
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter
from parika.core.forensic_log import (
    get_current_trace_id,
    log_plan,
    log_tool_start,
    log_tool_result,
    log_task_response_wrapping,
    log_synthesis_ready,
    log_synthesis_input,
    log_synthesis_result,
)

from .brain_request import BrainRequest
from .brain_response import BrainResponse
from .context_engine import (
    CompactionResult,
    ContextBundle,
    ContextMessage,
    HeuristicTokenEstimator,
    TokenBudget,
    TokenEstimator,
    assemble_context,
    compact,
    load_context_engine_config,
)
from .exceptions import ContextEngineUnavailableError, InvalidBrainRequestError
from .goal_result import GoalResult
from .exceptions import DependencyResolutionError

if TYPE_CHECKING:
    from parika.core.agent_orchestrator.agent_orchestrator import AgentOrchestrator
    from parika.core.configuration.configuration import Configuration
    from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
    from parika.core.memory_manager.memory_manager import MemoryManager
    from parika.core.planner.model_selection.experience_source import ExperienceSource
    from parika.core.provider_manager.chat_request import ChatRequest

ROOT_SOURCE_ID = "brain.execution"
"""
Stable, generic `source_id` for the root of every `handle()` call's
execution-progress tree. Named after the owning Core component
(`Brain`), matching the established convention of every other
progress/event-publishing Core component (`router.*`, `task.*`,
`tool.*`, `capability.*`, `provider.*`, ...); `Brain` is a permanent,
publicly documented Core component, not an internal implementation
detail, so this is consistent, not a leak.
"""

PLANNING_SOURCE_ID = "brain.planning"
"""`source_id` for the child node wrapping one `Planner.plan()` call."""

EXECUTE_GOAL_SOURCE_ID = "brain.execute_goal"
"""`source_id` for the child node wrapping one Goal's Task execution."""


class Brain:
    """
    PARIKA's central orchestration engine.

    Brain coordinates Planner and TaskManager to turn a BrainRequest
    into a final BrainResponse. It supervises execution across
    dependent Goals: a Goal whose dependency failed is skipped rather
    than attempted, while independent Goals continue to be attempted
    on a best-effort basis.

    Brain intentionally does not:

    - Replace specialized Core components. Planning, capability
      resolution, policy evaluation, and execution all remain owned
      by Planner, PolicyEngine, CapabilityResolver, TaskManager, and
      CapabilityExecutor.
    - Own responsibilities assigned to other managers.

    Brain reports pipeline failures through BrainResponse rather than
    raising, so that callers always receive a coherent final response.
    """

    def __init__(
        self,
        *,
        planner: Planner,
        task_manager: TaskManager,
        logger: Logger,
        event_bus: EventBus | None = None,
        memory_manager: "MemoryManager | None" = None,
        knowledge_manager: "KnowledgeManager | None" = None,
        experience_source: "ExperienceSource | None" = None,
        configuration: "Configuration | None" = None,
        token_estimator: TokenEstimator | None = None,
        agent_orchestrator: "AgentOrchestrator | None" = None,
        tool_manager: ToolManager | None = None,
        provider_manager: ProviderManager | None = None,
        capability_resolver: CapabilityResolver | None = None,
        policy_engine: PolicyEngine | None = None,
        resource_manager: ResourceManager | None = None,
    ) -> None:
        """
        Initialize the Brain.

        Args:
            planner:
                Planner used to turn Goals into an ExecutionPlan.

            task_manager:
                TaskManager used to create and execute Tasks for each
                planned Goal.

            logger:
                PARIKA Logger component.

            event_bus:
                Optional `EventBus`, used solely to publish this
                Brain's own `brain.execution.*` execution-progress
                tree (see this module's docstring). Omitting it leaves
                every other behavior of `handle()` completely
                unchanged; `handle()` simply reports no progress, via
                a `NullProgressReporter`. Brain never subscribes to
                the EventBus and never publishes any other event
                through it -- this is strictly narrower than the
                `event_bus` dependency other Core managers (Router,
                ToolManager, ...) hold.

            memory_manager:
                Optional MemoryManager, required only by
                `assemble_context()`. Omitting it leaves `handle()`'s
                existing behavior completely unchanged; calling
                `assemble_context()` without it raises
                `ContextEngineUnavailableError`.

            knowledge_manager:
                Optional KnowledgeManager, used by `assemble_context()`
                when both it and a message-shaped search text are
                available. Never required.

            experience_source:
                Optional `ExperienceSource` (the same structurally-typed
                Protocol `Planner` owns -- see
                `model_selection/experience_source.py`), used by
                `assemble_context()` to report a diagnostic Experience
                success-rate summary. Experience never contributes
                retrieved content here (see this module's
                `context_engine/retrieval_ordering.py` docstring);
                Brain never imports a concrete implementation.

            configuration:
                Optional Configuration, used to load the default
                `[context_engine]` `TokenBudget` (see
                `context_engine/budget.py`). Omitting it uses built-in
                defaults.

            token_estimator:
                Optional `TokenEstimator` override. Defaults to
                `HeuristicTokenEstimator` (stdlib, zero dependency).

            agent_orchestrator:
                Optional AgentOrchestrator for assigning agents to goals.
                If provided, agents are assigned before planning.

            tool_manager:
                Optional ToolManager for executing recovery actions
                (e.g., filesystem.search). Required for Goal Recovery.

            provider_manager:
                Optional ProviderManager for LLM-guided recovery
                reasoning. Required for Goal Recovery.

            capability_resolver:
                Optional CapabilityResolver for resolving recovery
                capabilities. Required for Goal Recovery.

            policy_engine:
                Optional PolicyEngine for authorizing recovery
                capabilities. Required for Goal Recovery.

            resource_manager:
                Optional ResourceManager for capability catalog context.
                Required for Goal Recovery.
        """

        self._planner = planner
        self._task_manager = task_manager
        self._logger = logger.get_logger(__name__)
        self._event_bus = event_bus
        self._memory_manager = memory_manager
        self._knowledge_manager = knowledge_manager
        self._experience_source = experience_source
        self._default_budget = load_context_engine_config(configuration)
        self._token_estimator = (
            token_estimator if token_estimator is not None else HeuristicTokenEstimator()
        )
        self._agent_orchestrator = agent_orchestrator
        self._tool_manager = tool_manager
        self._provider_manager = provider_manager
        self._capability_resolver = capability_resolver
        self._policy_engine = policy_engine
        self._resource_manager = resource_manager
        self._max_concurrent_goals = configuration.get("concurrency.max_concurrent_goals", 4) if configuration is not None else 4
        self._execution_mode = (
            configuration.get("concurrency.execution_mode", "parallel") if configuration is not None else "parallel"
        )
        self._max_recovery_attempts = configuration.get("recovery.max_attempts", 3) if configuration is not None else 3
        
        # Track recovery attempts per goal (goal_id -> attempt_count)
        self._recovery_attempts: dict[str, int] = {}
        # Track attempted inputs per goal to detect cycles
        self._recovery_attempted_inputs: dict[str, set[str]] = {}
        
        # Store the last BrainResponse for UI Context projection
        self._last_response: BrainResponse | None = None

    def _find_synthesis_goal_id(self, request: BrainRequest) -> str | None:
        """
        Find the synthesis goal ID from the request goals.
        
        Returns the goal_id of the synthesis goal (chat.respond with depends_on),
        or None if no synthesis goal is present.
        """
        for goal in request.goals:
            if self._is_synthesis_goal(goal):
                return goal.id
        return None

    def _is_synthesis_goal(self, goal: Goal) -> bool:
        """
        Check if a goal is a synthesis goal that should execute even with failed dependencies.
        
        A synthesis goal is typically a final response generation goal (chat.respond)
        that depends on multiple data-gathering goals. It should receive partial results
        and produce a response acknowledging any failures.
        """
        # Heuristic: chat.respond with dependencies is a synthesis goal
        if goal.capability_id == "chat.respond" and goal.depends_on:
            return True
        # Also treat any goal with metadata flag as synthesis
        if goal.metadata.get("is_synthesis_goal") is True:
            return True
        return False

    def _build_dependency_results(
        self,
        goal_id: str,
        deps: dict[str, set[str]],
        results: dict[str, GoalResult],
    ) -> dict[str, Any]:
        """Build a summary of dependency results for a synthesis goal."""
        dep_results = {}
        for dep_id in deps.get(goal_id, []):
            if dep_id in results:
                result = results[dep_id]
                if result.succeeded:
                    # Extract actual tool result from TaskResponse.outputs["result"].result
                    tool_result = None
                    if result.response is not None:
                        tool_response = result.response.outputs.get("result")
                        if tool_response is not None and hasattr(tool_response, "result"):
                            tool_result = tool_response.result
                        else:
                            tool_result = tool_response
                    dep_results[dep_id] = {
                        "status": "success",
                        "result": tool_result,
                    }
                elif result.skipped:
                    dep_results[dep_id] = {
                        "status": "skipped",
                        "reason": result.skip_reason,
                    }
                else:
                    dep_results[dep_id] = {
                        "status": "failed",
                        "error": str(result.failure) if result.failure else "Unknown error",
                    }
            else:
                dep_results[dep_id] = {
                    "status": "unknown",
                }
        return dep_results

    def _create_synthesis_execution_request(
        self,
        step: PlanStep,
        goal: Goal,
        dep_results: dict[str, Any],
    ) -> PlanStep:
        """
        Create a modified PlanStep for a synthesis goal with dependency results injected.
        """
        from parika.core.capability_executor.request import CapabilityExecutionRequest
        from parika.core.capability_executor.execution_target import ExecutionTarget
        from parika.core.planner.plan_step import PlanStep
        from parika.core.provider_manager.chat_request import ChatRequest
        from parika.core.provider_manager.chat_message import ChatMessage
        
        execution_request = step.execution_request
        backend_request = execution_request.backend_request
        
        # Inject dependency results into the backend request
        if isinstance(backend_request, ToolRequest):
            # For tool goals, add dependency results to arguments
            new_arguments = dict(backend_request.arguments)
            new_arguments["_dependency_results"] = dep_results
            new_backend_request = ToolRequest(
                arguments=new_arguments,
                metadata=backend_request.metadata,
            )
        elif isinstance(backend_request, ChatRequest):
            # For provider goals (ChatRequest), inject dependency results as a system message
            # Format the dependency results into a structured message
            dep_summary = self._format_dependency_results_for_synthesis(dep_results)
            system_message = ChatMessage(
                role="system",
                content=(
                    "DEPENDENCY RESULTS FOR SYNTHESIS:\n"
                    "The following are the results from the data-gathering goals this synthesis depends on.\n"
                    "Use these results to synthesize a final response. Note which goals failed.\n\n"
                    f"{dep_summary}"
                ),
            )
            # Insert the system message before the last message (typically the user message)
            # or at the beginning if there's only one message
            messages = list(backend_request.messages)
            if len(messages) >= 2:
                # Insert before the last message (user message)
                messages.insert(-1, system_message)
            else:
                # Prepend as first message
                messages.insert(0, system_message)
            
            new_backend_request = ChatRequest(
                messages=tuple(messages),
                tools=backend_request.tools,
                on_token=backend_request.on_token,
                options=getattr(backend_request, 'options', None),
            )
        else:
            # For other provider request types, pass through unchanged
            new_backend_request = backend_request
        
        new_execution_request = CapabilityExecutionRequest(
            resolution=execution_request.resolution,
            target=execution_request.target,
            backend_request=new_backend_request,
            metadata=execution_request.metadata,
        )
        
        return PlanStep(
            goal_id=step.goal_id,
            execution_request=new_execution_request,
            depends_on=step.depends_on,
        )

    def _create_resolved_execution_request(
        self,
        step: PlanStep,
        goal: Goal,
        resolved_inputs: Mapping[str, Any],
    ) -> PlanStep:
        """
        Create a modified PlanStep for a non-synthesis goal with resolved inputs.

        Replaces the backend request's arguments with the resolved inputs.
        """
        from parika.core.capability_executor.request import CapabilityExecutionRequest
        from parika.core.tool_manager.request import ToolRequest
        
        execution_request = step.execution_request
        backend_request = execution_request.backend_request
        
        if isinstance(backend_request, ToolRequest):
            # For tool goals, replace arguments with resolved inputs
            new_backend_request = ToolRequest(
                arguments=dict(resolved_inputs),
                metadata=backend_request.metadata,
            )
        else:
            # For provider goals, we don't modify (they use different injection)
            new_backend_request = backend_request
        
        new_execution_request = CapabilityExecutionRequest(
            resolution=execution_request.resolution,
            target=execution_request.target,
            backend_request=new_backend_request,
            metadata=execution_request.metadata,
        )
        
        return PlanStep(
            goal_id=step.goal_id,
            execution_request=new_execution_request,
            depends_on=step.depends_on,
        )

    def _format_dependency_results_for_synthesis(self, dep_results: dict[str, Any]) -> str:
        """Format dependency results into a human-readable summary for the synthesis model."""
        lines = []
        for dep_id, result in dep_results.items():
            status = result.get("status", "unknown")
            if status == "success":
                # Include a summary of the result
                result_data = result.get("result")
                if result_data:
                    lines.append(f"✓ {dep_id}: SUCCESS - {self._summarize_result(result_data)}")
                else:
                    lines.append(f"✓ {dep_id}: SUCCESS")
            elif status == "failed":
                error = result.get("error", "Unknown error")
                lines.append(f"✗ {dep_id}: FAILED - {error}")
            elif status == "skipped":
                reason = result.get("reason", "Dependency failed")
                lines.append(f"⊘ {dep_id}: SKIPPED - {reason}")
            else:
                lines.append(f"? {dep_id}: {status.upper()}")
        return "\n".join(lines)

    def _summarize_result(self, result: Any) -> str:
        """Create a brief summary of a tool result."""
        if isinstance(result, dict):
            # Try to extract key fields
            if "result" in result:
                return str(result["result"])
            return str(result)

        if isinstance(result, (list, tuple)):
            summaries = []
            for item in result:
                if isinstance(item, dict):
                    parts = []

                    if item.get("title"):
                        parts.append(f"title: {item['title']}")

                    if item.get("snippet"):
                        parts.append(f"snippet: {item['snippet']}")

                    if item.get("url"):
                        parts.append(f"url: {item['url']}")

                    if parts:
                        summaries.append(" | ".join(parts))
                    else:
                        summaries.append(str(item))
                else:
                    summaries.append(str(item))

            return "\n".join(summaries)

        return str(result)

    # ------------------------------------------------------------------
    # Goal Recovery
    # ------------------------------------------------------------------

    def _is_recoverable_failure(self, failure: BaseException) -> bool:
        """
        Determine if a failure is recoverable through Goal Recovery.

        Only treats tool-specific "not found" exceptions as recoverable,
        by checking the exception type hierarchy. String matching is
        avoided to prevent false positives (e.g., "user not found" in
        database, "page not found" in web).
        """
        # Check for tool-specific not-found exception types
        # These are wrapped in ToolExecutionError -> CapabilityExecutionError -> TaskExecutionError
        # We need to unwrap to find the root cause
        current = failure
        while current is not None:
            type_name = type(current).__name__
            # Tool-specific not-found exceptions
            recoverable_types = {
                "FilesystemPathNotFoundError",
                "LocationNotFoundError",
                "MediaSourceNotFoundError",
                "ExpenseNotFoundError",
                "CodingIndexNotFoundError",
                "UnknownTimezoneError",
                "WebSearchProviderUnavailableError",
            }
            if type_name in recoverable_types:
                return True
            
            # Check for base not-found exceptions
            if "NotFoundError" in type_name and "Provider" not in type_name:
                return True
            
            # Move to cause
            current = getattr(current, "__cause__", None)
        
        return False

    def _get_recovery_attempts(self, goal_id: str) -> int:
        """Get the number of recovery attempts for a goal."""
        return self._recovery_attempts.get(goal_id, 0)

    def _increment_recovery_attempts(self, goal_id: str) -> int:
        """Increment and return the recovery attempt count for a goal."""
        count = self._recovery_attempts.get(goal_id, 0) + 1
        self._recovery_attempts[goal_id] = count
        return count

    def _reset_recovery_attempts(self, goal_id: str) -> None:
        """Reset recovery attempts for a goal (called on success)."""
        self._recovery_attempts.pop(goal_id, None)
        self._recovery_attempted_inputs.pop(goal_id, None)

    def _get_workspace_root(self, path: str) -> str:
        """
        Resolve the workspace root for a given path using the existing
        WorkspacePermissionManager logic.

        This derives the workspace from the path itself, ensuring
        recovery stays within the same project boundary as the original goal.
        """
        return str(WorkspacePermissionManager._resolve_workspace_key(path))

    def _get_recovery_capabilities(self, failure_context: str = "") -> list[tuple[str, str, str]]:
        """
        Get capabilities suitable for recovery, filtered by policy and
        ranked by relevance to the failure context.

        Uses CapabilityCatalog for relevance ranking and PolicyEngine
        for authorization. Does not expose arbitrary capabilities.
        """
        if self._tool_manager is None or self._capability_registry is None:
            return []

        # Get all enabled TOOL capabilities
        all_definitions = self._capability_registry.find(
            category=CapabilityCategory.TOOL,
            enabled=True,
        )

        # Filter by PolicyEngine
        allowed_cap_ids = []
        for definition in all_definitions:
            if self._policy_engine is None:
                allowed_cap_ids.append(definition.id)
                continue

            policy_request = PolicyEvaluationRequest(
                rules=(),
                context={
                    "capability_id": definition.id,
                    "capability_category": CapabilityCategory.TOOL.value,
                    "inputs": {"recovery": True, "failure_context": failure_context},
                    "resource_snapshot": self._resource_manager.get_resource_snapshot() if self._resource_manager else None,
                },
                default_effect=PolicyEffect.ALLOW,
            )
            decision = self._policy_engine.evaluate(policy_request)
            if decision.is_allowed:
                allowed_cap_ids.append(definition.id)

        if not allowed_cap_ids:
            return []

        # Rank by relevance using CapabilityCatalog
        allowed_definitions = tuple(d for d in all_definitions if d.id in allowed_cap_ids)
        if not allowed_definitions:
            return []

        catalog = CapabilityCatalog()
        ranked = catalog.retrieve(allowed_definitions, text=f"Find missing resource: {failure_context}")

        return [(d.id, d.name, d.description) for d in ranked]

    def _build_recovery_prompt(
        self,
        goal: Goal,
        failure: BaseException,
        step: PlanStep,
        recovery_capabilities: list[tuple[str, str, str]],
    ) -> str:
        """Build the prompt for LLM-guided recovery."""
        original_inputs = dict(goal.inputs)
        
        capabilities_desc = []
        for cap_id, cap_name, cap_desc in recovery_capabilities:
            capabilities_desc.append(f"- {cap_id}: {cap_desc}")

        return f"""GOAL RECOVERY NEEDED

Original Goal: {goal.id} ({goal.capability_id})
Original Inputs: {original_inputs}
Failure: {type(failure).__name__}: {failure}

Available Recovery Capabilities:
{chr(10).join(capabilities_desc)}

The original goal failed. Your task is to determine a recovery action using ONE of the available capabilities above.
The recovery action should discover or locate the correct resource/input.

Respond with a JSON object containing:
{{
  "recovery_capability": "capability_id",
  "recovery_inputs": {{"key": "value"}},
  "reasoning": "brief explanation"
}}

The recovery action will be executed and its result used to correct the original goal's inputs for retry.
"""

    async def _execute_recovery_action(
        self,
        goal: Goal,
        failure: BaseException,
        step: PlanStep,
        progress: ProgressReporter,
        failed_path_context: str = "",
    ) -> dict[str, Any] | None:
        """
        Execute the full recovery sequence: LLM reasoning -> capability execution -> correction.

        Returns corrected inputs for retrying the original goal, or None if recovery fails.
        """
        if self._provider_manager is None or self._tool_manager is None or self._capability_resolver is None:
            self._logger.warning(
                "Goal Recovery unavailable: required components not configured."
            )
            return None

        # Get recovery capabilities filtered by policy and ranked by relevance
        recovery_capabilities = self._get_recovery_capabilities(failed_path_context)

        if not recovery_capabilities:
            self._logger.warning("No recovery capabilities available for goal '%s'.", goal.id)
            return None

        # Build recovery prompt
        recovery_prompt = self._build_recovery_prompt(goal, failure, step, recovery_capabilities)

        # Invoke LLM to determine recovery action
        recovery_plan = await self._invoke_llm_for_recovery(recovery_prompt, recovery_capabilities)

        if not recovery_plan:
            return None

        # Execute the recovery capability
        recovery_result = await self._execute_recovery_capability(recovery_plan, progress)

        if not recovery_result:
            return None

        # Extract corrected inputs from recovery result via LLM reasoning
        corrected_inputs = self._extract_corrected_inputs(
            goal, failure, recovery_plan, recovery_result
        )

        return corrected_inputs

    async def _invoke_llm_for_recovery(
        self,
        prompt: str,
        recovery_capabilities: list[tuple[str, str, str]],
    ) -> dict[str, Any] | None:
        """
        Invoke LLM to determine recovery action using the normal Brain
        pipeline via a synthetic chat.respond Goal.
        """
        if self._provider_manager is None:
            self._logger.warning("Goal Recovery unavailable: provider_manager not configured.")
            return None

        # Build capability list for LLM
        capabilities_desc = []
        for cap_id, cap_name, cap_desc in recovery_capabilities:
            capabilities_desc.append(f"- {cap_id}: {cap_desc}")

        system_prompt = (
            "You are a recovery planner for an AI orchestration system. "
            "A goal failed. Select ONE recovery capability and provide inputs to find the correct resource. "
            "Respond ONLY with valid JSON as specified."
        )
        
        recovery_prompt = f"""Available Recovery Capabilities:
{chr(10).join(capabilities_desc)}

{prompt}"""

        # Create synthetic recovery reasoning Goal
        recovery_goal = Goal(
            id="recovery_reasoning",
            capability_id="chat.respond",
            inputs={"message": recovery_prompt},
            metadata={"recovery_reasoning": True, "system_prompt": system_prompt},
        )

        try:
            # Execute via normal Brain pipeline (uses Planner.plan + normal model selection)
            request = BrainRequest(goals=(recovery_goal,))
            response = self.handle(request)

            if not response.succeeded or not response.results:
                self._logger.warning("Recovery LLM reasoning failed: %s", response.results[0].failure if response.results else "no results")
                return None

            # Extract LLM response content
            result = response.results[0]
            if result.response and result.response.outputs:
                content = result.response.outputs.get("result")
                if hasattr(content, "content"):
                    content = content.content
                elif hasattr(content, "message") and hasattr(content.message, "content"):
                    content = content.message.content
                else:
                    content = str(content)
            else:
                return None

            # Parse JSON from response
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()
            
            recovery_plan = json.loads(content)
            
            # Validate capability is in allowed list
            allowed_cap_ids = {cap_id for cap_id, _, _ in recovery_capabilities}
            if recovery_plan.get("recovery_capability") not in allowed_cap_ids:
                self._logger.warning(
                    "Recovery LLM selected unauthorized capability: %s",
                    recovery_plan.get("recovery_capability")
                )
                return None

            return recovery_plan

        except Exception as e:
            self._logger.exception("Failed to invoke LLM for recovery: %s", e)
            return None

    async def _execute_recovery_capability(
        self,
        recovery_plan: dict[str, Any],
        progress: ProgressReporter,
    ) -> Any | None:
        """Execute a recovery capability via the normal public execution pipeline."""
        capability_id = recovery_plan.get("recovery_capability")
        inputs = recovery_plan.get("recovery_inputs", {})

        if not capability_id or self._capability_resolver is None:
            return None

        try:
            from parika.core.capability_resolver.capability_request import CapabilityRequest
            from parika.core.capability_executor.request import CapabilityExecutionRequest
            from parika.core.capability_executor.execution_target import ExecutionTarget
            from parika.core.tool_manager.request import ToolRequest

            # Resolve capability via public API
            resolution = self._capability_resolver.resolve(
                CapabilityRequest(capability_id=capability_id)
            )

            # Select tool via public ToolManager (same logic as Planner._select_tool)
            tool = None
            for t in self._tool_manager.get_all():
                if t.enabled and capability_id in t.capabilities:
                    tool = t
                    break
            
            if tool is None:
                self._logger.warning("No enabled tool found for capability: %s", capability_id)
                return None

            target = ExecutionTarget(
                backend=resolution.execution_backend,
                identifier=tool.id,
            )

            backend_request = ToolRequest(
                arguments=inputs,
                metadata={"recovery_action": True},
            )

            execution_request = CapabilityExecutionRequest(
                resolution=resolution,
                target=target,
                backend_request=backend_request,
                metadata={"recovery_action": True},
            )

            # Create and execute task
            task = self._task_manager.create(
                TaskRequest(
                    capability_id=capability_id,
                    inputs=inputs,
                    metadata={"recovery_action": True},
                ),
            )

            executed_task = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._task_manager.execute(task.id, execution_request),
            )

            if executed_task.response and executed_task.response.outputs:
                return executed_task.response.outputs.get("result")
            return None

        except Exception as e:
            self._logger.exception("Recovery capability execution failed: %s", e)
            return None

    def _extract_corrected_inputs(
        self,
        goal: Goal,
        failure: BaseException,
        recovery_plan: dict[str, Any],
        recovery_result: Any,
    ) -> dict[str, Any] | None:
        """
        Extract corrected inputs for the original goal from recovery result.

        Uses LLM reasoning over the raw recovery result to determine
        the corrected inputs, rather than hardcoding field extraction.
        """
        if not recovery_result:
            return None

        # Use LLM to reason about the recovery result and select corrected inputs
        correction_prompt = f"""RECOVERY RESULT ANALYSIS

Original Goal: {goal.id} ({goal.capability_id})
Original Inputs: {dict(goal.inputs)}
Original Failure: {type(failure).__name__}: {failure}
Recovery Action: {recovery_plan.get('recovery_capability')} with inputs {recovery_plan.get('recovery_inputs')}
Recovery Result: {recovery_result}

The recovery action was executed to find the correct resource. Analyze the result and determine the corrected inputs for the original goal.

Respond with a JSON object containing:
{{
  "corrected_inputs": {{"key": "value"}},
  "reasoning": "brief explanation of why this correction is correct"
}}

If no valid correction can be determined, respond with:
{{
  "corrected_inputs": null,
  "reasoning": "explanation"
}}
"""

        try:
            correction_goal = Goal(
                id="recovery_correction",
                capability_id="chat.respond",
                inputs={"message": correction_prompt},
                metadata={"recovery_correction": True},
            )

            request = BrainRequest(goals=(correction_goal,))
            response = self.handle(request)

            if not response.succeeded or not response.results:
                return None

            result = response.results[0]
            if result.response and result.response.outputs:
                content = result.response.outputs.get("result")
                if hasattr(content, "content"):
                    content = content.content
                elif hasattr(content, "message") and hasattr(content.message, "content"):
                    content = content.message.content
                else:
                    content = str(content)
            else:
                return None

            content = content.strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()
            
            correction = json.loads(content)
            corrected = correction.get("corrected_inputs")
            
            if corrected is None:
                self._logger.info("Recovery LLM determined no valid correction: %s", correction.get("reasoning"))
                return None

            self._logger.info(
                "Goal Recovery: LLM selected corrected inputs: %s",
                corrected
            )
            return corrected

        except Exception as e:
            self._logger.exception("Failed to extract corrected inputs: %s", e)
            return None

    def _hash_inputs(self, inputs: dict[str, Any]) -> str:
        """Create a hash of inputs for cycle detection."""
        # Create deterministic string representation
        serialized = json.dumps(inputs, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]

    def _check_recovery_cycle(self, goal_id: str, inputs: dict[str, Any]) -> bool:
        """Check if these inputs have been attempted before for this goal."""
        if goal_id not in self._recovery_attempted_inputs:
            self._recovery_attempted_inputs[goal_id] = set()
        
        input_hash = self._hash_inputs(inputs)
        if input_hash in self._recovery_attempted_inputs[goal_id]:
            self._logger.warning(
                "Goal Recovery: Cycle detected for goal '%s' - inputs already attempted",
                goal_id
            )
            return True
        
        self._recovery_attempted_inputs[goal_id].add(input_hash)
        return False

    _DEP_REF_PATTERN = re.compile(r'\{([a-zA-Z_][a-zA-Z0-9_]*)\.result([^}]*)\}')

    def _resolve_dependency_references(
        self,
        goal_id: str,
        inputs: Mapping[str, Any],
        deps: dict[str, set[str]],
        results: dict[str, GoalResult],
    ) -> dict[str, Any]:
        """
        Resolve {goal_id.result.path} style references in goal inputs.

        Supports:
        - {goal_0.result.path} -> scalar value
        - {goal_0.result.matches[0]} -> indexed list access
        - {goal_0.result.some.nested.path} -> nested dict access

        Only resolves references to goals that are declared dependencies of the current goal.

        Raises:
            DependencyResolutionError: If reference cannot be resolved.
        """
        # Build a map of available dependency results for declared dependencies
        declared_deps = deps.get(goal_id, set())
        dep_results_map = {}
        for dep_id in declared_deps:
            if dep_id not in results:
                raise DependencyResolutionError(
                    f"Goal '{goal_id}' depends on '{dep_id}' but no result is available."
                )
            result = results[dep_id]
            if not result.succeeded:
                raise DependencyResolutionError(
                    f"Goal '{goal_id}' depends on '{dep_id}' which did not succeed "
                    f"(status: {'skipped' if result.skipped else 'failed'})."
                )
            # Extract actual tool result (same logic as _build_dependency_results)
            tool_result = None
            if result.response is not None:
                tool_response = result.response.outputs.get("result")
                if tool_response is not None and hasattr(tool_response, "result"):
                    tool_result = tool_response.result
                else:
                    tool_result = tool_response
            dep_results_map[dep_id] = tool_result

        def resolve_value(value: Any) -> Any:
            """Recursively resolve references in a value."""
            if isinstance(value, str):
                return self._resolve_string_references(value, goal_id, dep_results_map, declared_deps)
            elif isinstance(value, Mapping):
                return {k: resolve_value(v) for k, v in value.items()}
            elif isinstance(value, (list, tuple)):
                return [resolve_value(item) for item in value]
            else:
                return value

        return resolve_value(inputs)

    def _resolve_string_references(
        self,
        value: str,
        goal_id: str,
        dep_results_map: dict[str, Any],
        declared_deps: set[str],
    ) -> Any:
        """
        Resolve all {{...}} references in a string value.

        If the entire string is a single reference that resolves to a non-string,
        return the resolved value directly (preserving type).
        Otherwise, substitute references within the string.
        """
        # Check for unmatched braces - detect { without matching }
        open_braces = value.count('{')
        close_braces = value.count('}')
        if open_braces != close_braces:
            raise DependencyResolutionError(
                f"Goal '{goal_id}': Unmatched braces in input '{value}'. "
                f"Every '{{' must have a matching '}}'."
            )
        
        # Find all references in the string
        matches = list(self._DEP_REF_PATTERN.finditer(value))
        
        if not matches:
            # No valid references found, but we already validated brace matching
            return value

        # If the entire string is a single reference, return the resolved value directly
        if len(matches) == 1 and matches[0].span() == (0, len(value)):
            return self._resolve_single_reference(matches[0], goal_id, dep_results_map, declared_deps)

        # Otherwise, substitute each reference in the string
        result_parts = []
        last_end = 0
        for match in matches:
            start, end = match.span()
            result_parts.append(value[last_end:start])
            resolved = self._resolve_single_reference(match, goal_id, dep_results_map, declared_deps)
            result_parts.append(str(resolved))
            last_end = end
        result_parts.append(value[last_end:])
        return "".join(result_parts)

    def _resolve_single_reference(
        self,
        match: re.Match,
        goal_id: str,
        dep_results_map: dict[str, Any],
        declared_deps: set[str],
    ) -> Any:
        """Resolve a single {goal_id.result...} reference."""
        full_match = match.group(0)
        dep_goal_id = match.group(1)
        path_str = match.group(2)  # This is the path part like ".path" or ".matches[0]"
        
        # path_str includes the leading dot, remove it
        if path_str.startswith('.'):
            path_str = path_str[1:]
        
        if not path_str:
            raise DependencyResolutionError(
                f"Goal '{goal_id}': Empty dependency reference '{full_match}'. "
                f"Must specify a result field, e.g. '{{{dep_goal_id}.result.path}}'."
            )
        
        # Check if the dependency goal is declared
        if dep_goal_id not in declared_deps:
            raise DependencyResolutionError(
                f"Goal '{goal_id}': Reference to undeclared dependency '{dep_goal_id}' "
                f"in '{full_match}'. Declared dependencies: {sorted(declared_deps)}."
            )
        
        # Check if the dependency goal has a result
        if dep_goal_id not in dep_results_map:
            raise DependencyResolutionError(
                f"Goal '{goal_id}': Dependency '{dep_goal_id}' has no result available."
            )
        
        dep_result = dep_results_map[dep_goal_id]
        if dep_result is None:
            raise DependencyResolutionError(
                f"Goal '{goal_id}': Dependency '{dep_goal_id}' has no result data."
            )
        
        # Parse the path (supports .field and [index] notation)
        return self._extract_value_by_path(dep_result, path_str, dep_goal_id, full_match, goal_id)

    def _extract_value_by_path(
        self,
        data: Any,
        path: str,
        dep_goal_id: str,
        full_match: str,
        goal_id: str,
    ) -> Any:
        """Extract a value from data using a path like '.field' or '.field[0].subfield'."""
        if not path:
            return data
        
        current = data
        # Split by . but respect brackets
        # Simple approach: replace [ with .[ then split by .
        # But we need to handle nested brackets properly
        # Let's use a simple state machine
        
        parts = []
        current_part = ""
        in_bracket = False
        
        for char in path:
            if char == '[' and not in_bracket:
                if current_part:
                    parts.append(current_part)
                    current_part = ""
                in_bracket = True
                current_part += char
            elif char == ']' and in_bracket:
                in_bracket = False
                current_part += char
                parts.append(current_part)
                current_part = ""
            elif char == '.' and not in_bracket:
                if current_part:
                    parts.append(current_part)
                    current_part = ""
            else:
                current_part += char
        
        if current_part:
            parts.append(current_part)
        
        # Remove leading empty part if path starts with .
        if parts and parts[0] == '':
            parts = parts[1:]
        
        for part in parts:
            if part.startswith('[') and part.endswith(']'):
                # Index access
                index_str = part[1:-1]
                try:
                    index = int(index_str)
                except ValueError:
                    raise DependencyResolutionError(
                        f"Goal '{goal_id}': Invalid index '{index_str}' in reference '{full_match}'. "
                        f"Index must be an integer."
                    )
                if not isinstance(current, (list, tuple)):
                    raise DependencyResolutionError(
                        f"Goal '{goal_id}': Cannot index into non-list value in reference '{full_match}'. "
                        f"Expected list at path '{path}', got {type(current).__name__}."
                    )
                if index < 0 or index >= len(current):
                    raise DependencyResolutionError(
                        f"Goal '{goal_id}': Index {index} out of bounds in reference '{full_match}'. "
                        f"List has {len(current)} elements."
                    )
                current = current[index]
            else:
                # Field access
                if not isinstance(current, dict):
                    raise DependencyResolutionError(
                        f"Goal '{goal_id}': Cannot access field '{part}' on non-dict value in reference '{full_match}'. "
                        f"Expected dict at path, got {type(current).__name__}."
                    )
                if part not in current:
                    raise DependencyResolutionError(
                        f"Goal '{goal_id}': Field '{part}' not found in dependency '{dep_goal_id}' result "
                        f"for reference '{full_match}'. Available fields: {sorted(current.keys())}."
                    )
                current = current[part]
        
        return current

        if isinstance(result, (list, tuple)):
            summaries = []
            for item in result:
                if isinstance(item, dict):
                    parts = []

                    if item.get("title"):
                        parts.append(f"title: {item['title']}")

                    if item.get("snippet"):
                        parts.append(f"snippet: {item['snippet']}")

                    if item.get("url"):
                        parts.append(f"url: {item['url']}")

                    if parts:
                        summaries.append(" | ".join(parts))
                    else:
                        summaries.append(str(item))
                else:
                    summaries.append(str(item))

            return "\n".join(summaries)

        return str(result)

    def handle(self, request: BrainRequest) -> BrainResponse:
        """
        Handle a BrainRequest and produce a final BrainResponse.

        Args:
            request:
                Request carrying the Goals to plan and supervise.

        Returns:
            The final BrainResponse. Planning and execution failures
            are captured within the response rather than raised.

        Raises:
            InvalidBrainRequestError:
                If `request` is not a BrainRequest instance.
        """

        if not isinstance(request, BrainRequest):
            raise InvalidBrainRequestError(
                "Expected a BrainRequest instance."
            )

        self._logger.debug(
            "Brain received request '%s' with %d goal(s).",
            request.id,
            len(request.goals),
        )

        progress = self._root_progress_reporter()
        progress.started(
            message=f"Handling request with {len(request.goals)} goal(s)."
        )

        planning_progress = progress.child(PLANNING_SOURCE_ID)
        planning_progress.started()

        # Assign agents to goals before planning if orchestrator is available
        if self._agent_orchestrator is not None:
            agent_goals = self._agent_orchestrator.assign_agents_to_goals(request.goals)
            # Extract goals with agent metadata attached
            request = BrainRequest(goals=tuple(a.goal for a in agent_goals))

        try:
            plan = self._planner.plan(request.goals)

        except Exception as ex:
            self._logger.exception(
                "Planning failed for request '%s'.",
                request.id,
            )

            planning_progress.failed(message=str(ex))
            progress.failed(message="Planning failed.")

            return BrainResponse(
                request_id=request.id,
                plan_id=None,
                results=(),
                planning_failure=ex,
            )

        planning_progress.completed()

        # FORENSIC: Log execution plan
        trace_id = get_current_trace_id()
        if trace_id:
            steps_data = []
            for step in plan.steps:
                steps_data.append({
                    "goal_id": step.goal_id,
                    "capability": step.execution_request.resolution.definition.id,
                    "backend": step.execution_request.target.backend.value,
                    "dependencies": list(step.depends_on),
                })
            log_plan(
                trace_id=trace_id,
                plan_id=plan.id,
                steps=steps_data,
            )

        try:
            results = self._supervise(request, plan, progress)

        except Exception as ex:
            self._logger.exception(
                "Execution failed for request '%s'.",
                request.id,
            )

            progress.failed(message=str(ex))

            raise

        response = BrainResponse(
            request_id=request.id,
            plan_id=plan.id,
            results=results,
            synthesis_goal_id=self._find_synthesis_goal_id(request),
        )

        # Store the response for UI Context projection
        self._last_response = response

        self._logger.debug(
            "Brain completed request '%s' (succeeded=%s).",
            request.id,
            response.succeeded,
        )

        progress.completed(
            message=f"succeeded={response.succeeded}",
            succeeded=response.succeeded,
            request_id=request.id,
        )

        return response
    
    @property
    def last_response(self) -> BrainResponse | None:
        """
        Get the last BrainResponse produced by this Brain instance.
        
        This is used by the UI Context Projector to project the real
        execution state (request status, synthesis, dependencies, etc.)
        without duplicating Brain logic in the projector.
        
        Returns:
            The most recent BrainResponse, or None if no request has been handled yet.
        """
        return self._last_response

    def _root_progress_reporter(self) -> ProgressReporter:
        """
        Build this `handle()` call's root execution-progress reporter.

        Returns a real `ProgressReporter` publishing through the
        `EventBus` supplied at construction, or a `NullProgressReporter`
        (publishes nothing) when none was supplied -- see this
        module's docstring.
        """

        if self._event_bus is None:
            return NullProgressReporter(ROOT_SOURCE_ID)

        return ProgressReporter(self._event_bus, ROOT_SOURCE_ID)

    # ------------------------------------------------------------------
    # Execution Supervision
    # ------------------------------------------------------------------

    async def _execute_goal_async(
        self,
        goal: Goal,
        step: PlanStep,
        progress: ProgressReporter,
    ) -> GoalResult:
        """
        Create and execute a single Task for a planned Goal (async version).

        Execution failures are captured into the returned GoalResult
        rather than raised. Includes bounded Goal Recovery for recoverable failures.
        """

        # Recovery loop: initial attempt + max_recovery_attempts retries
        max_attempts = 1 + self._max_recovery_attempts
        current_inputs = dict(goal.inputs)
        current_step = step
        last_failure: BaseException | None = None

        # Extract failed path context for workspace boundary
        failed_path_context = ""
        for key, value in goal.inputs.items():
            if isinstance(value, str) and ("path" in key.lower() or "file" in key.lower() or "url" in key.lower()):
                failed_path_context = value
                break

        for attempt in range(max_attempts):
            is_recovery_attempt = attempt > 0
            if is_recovery_attempt:
                # Check for cycle before attempting recovery
                if self._check_recovery_cycle(goal.id, current_inputs):
                    self._logger.warning(
                        "Goal Recovery: Cycle detected, terminating recovery for goal '%s'",
                        goal.id
                    )
                    break
                
                self._increment_recovery_attempts(goal.id)
                self._logger.info(
                    "Goal Recovery: Attempt %d/%d for goal '%s'",
                    attempt, self._max_recovery_attempts, goal.id
                )

                # Update step with corrected inputs for retry
                from parika.core.capability_executor.request import CapabilityExecutionRequest
                from parika.core.tool_manager.request import ToolRequest

                execution_request = current_step.execution_request
                backend_request = execution_request.backend_request

                if isinstance(backend_request, ToolRequest):
                    new_backend_request = ToolRequest(
                        arguments=current_inputs,
                        metadata=backend_request.metadata,
                    )
                    current_step = PlanStep(
                        goal_id=current_step.goal_id,
                        execution_request=CapabilityExecutionRequest(
                            resolution=execution_request.resolution,
                            target=execution_request.target,
                            backend_request=new_backend_request,
                            metadata=execution_request.metadata,
                        ),
                        depends_on=current_step.depends_on,
                    )

            task = self._task_manager.create(
                TaskRequest(
                    capability_id=goal.capability_id,
                    inputs=current_inputs,
                    context_id=goal.context_id,
                    metadata=goal.metadata,
                ),
            )

            goal_progress = progress.child(EXECUTE_GOAL_SOURCE_ID, task_id=task.id)
            attempt_msg = f" (recovery attempt {attempt})" if is_recovery_attempt else ""
            goal_progress.started(message=f"Executing goal '{goal.id}'{attempt_msg}.")

            # FORENSIC: Log tool start
            trace_id = get_current_trace_id()
            start_time = time.perf_counter()
            if trace_id:
                backend_request = current_step.execution_request.backend_request
                arguments = {}
                if hasattr(backend_request, 'arguments'):
                    arguments = backend_request.arguments
                elif hasattr(backend_request, 'messages'):
                    arguments = {"messages": [{"role": m.role, "content": m.content} for m in backend_request.messages]}

                log_tool_start(
                    trace_id=trace_id,
                    goal_id=goal.id,
                    task_id=task.id,
                    capability_id=goal.capability_id,
                    tool_id=current_step.execution_request.target.identifier,
                    arguments=arguments,
                    backend=current_step.execution_request.target.backend.value,
                )

            try:
                # Run synchronous execute in thread pool to avoid blocking event loop
                executed_task = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._task_manager.execute(task.id, current_step.execution_request),
                )

            except Exception as ex:
                self._logger.exception(
                    "Execution failed for goal '%s' (task '%s')%s.",
                    goal.id,
                    task.id,
                    " during recovery" if is_recovery_attempt else "",
                )

                goal_progress.failed(message=str(ex))

                # FORENSIC: Log tool result (failure)
                if trace_id:
                    execution_time = time.perf_counter() - start_time
                    log_tool_result(
                        trace_id=trace_id,
                        goal_id=goal.id,
                        task_id=task.id,
                        capability_id=goal.capability_id,
                        tool_id=current_step.execution_request.target.identifier,
                        success=False,
                        result=None,
                        exception=str(ex),
                        execution_time=execution_time,
                    )

                last_failure = ex

                # Check if this failure is recoverable and we have attempts remaining
                if is_recovery_attempt or attempt < max_attempts - 1:
                    if self._is_recoverable_failure(ex):
                        self._logger.info(
                            "Goal Recovery: Recoverable failure detected for goal '%s': %s",
                            goal.id, ex
                        )
                        # Attempt recovery with workspace boundary enforcement
                        corrected_inputs = await self._execute_recovery_action(
                            goal, ex, current_step, progress, failed_path_context
                        )
                        if corrected_inputs:
                            current_inputs = corrected_inputs
                            continue  # Retry with corrected inputs
                        else:
                            self._logger.warning(
                                "Goal Recovery: Recovery action failed or returned no correction for goal '%s'",
                                goal.id
                            )
                    else:
                        self._logger.debug(
                            "Goal Recovery: Failure for goal '%s' is not recoverable: %s",
                            goal.id, ex
                        )

                # No more recovery attempts or not recoverable - return failure
                return GoalResult(
                    goal_id=goal.id,
                    capability_id=goal.capability_id,
                    task_id=task.id,
                    status=self._task_manager.get(task.id).status,
                    failure=last_failure,
                    depends_on=tuple(current_step.depends_on),
                )

            # Success!
            goal_progress.completed()

            # FORENSIC: Log tool result (success)
            if trace_id:
                execution_time = time.perf_counter() - start_time
                result_data = None
                if executed_task.response and executed_task.response.outputs:
                    result_data = executed_task.response.outputs.get("result")

                log_tool_result(
                    trace_id=trace_id,
                    goal_id=goal.id,
                    task_id=executed_task.id,
                    capability_id=goal.capability_id,
                    tool_id=current_step.execution_request.target.identifier,
                    success=True,
                    result=result_data,
                    execution_time=execution_time,
                )

                # FORENSIC: Log task response wrapping
                raw_backend = result_data
                cap_exec_response = None
                task_response_data = None
                goal_result_response_type = None

                if executed_task.response:
                    cap_exec_response = {
                        "backend_response": str(executed_task.response.outputs.get("result"))[:500] if executed_task.response.outputs else None,
                        "metadata": dict(executed_task.response.metadata) if executed_task.response.metadata else {},
                        "duration_seconds": executed_task.response.duration_seconds,
                    }
                    task_response_data = {
                        "outputs": dict(executed_task.response.outputs) if executed_task.response.outputs else {},
                        "metadata": dict(executed_task.response.metadata) if executed_task.response.metadata else {},
                        "duration_seconds": executed_task.response.duration_seconds,
                    }

                if executed_task.response and executed_task.response.outputs:
                    goal_result_response_type = type(executed_task.response.outputs.get("result")).__name__

                log_task_response_wrapping(
                    trace_id=trace_id,
                    goal_id=goal.id,
                    task_id=executed_task.id,
                    capability_id=goal.capability_id,
                    raw_backend_result=raw_backend,
                    capability_execution_response=cap_exec_response,
                    task_response=task_response_data,
                    goal_result_response_type=goal_result_response_type,
                )

            # Reset recovery attempts on success
            self._reset_recovery_attempts(goal.id)

            return GoalResult(
                goal_id=goal.id,
                capability_id=goal.capability_id,
                task_id=executed_task.id,
                status=executed_task.status,
                response=executed_task.response,
                depends_on=tuple(current_step.depends_on),
            )

        # Should not reach here, but handle gracefully
        return GoalResult(
            goal_id=goal.id,
            capability_id=goal.capability_id,
            task_id=None,
            status=None,
            failure=last_failure or RuntimeError("Goal execution failed after all recovery attempts"),
            depends_on=tuple(step.depends_on),
        )

    async def _supervise_async(
        self,
        request: BrainRequest,
        plan: ExecutionPlan,
        progress: ProgressReporter,
    ) -> tuple[GoalResult, ...]:
        """
        Execute PlanSteps with dependency-aware concurrency.

        Independent goals execute concurrently. Dependent goals wait for their
        dependencies to complete successfully. Failed dependencies cause
        dependent goals to be skipped.
        """

        goals_by_id = {goal.id: goal for goal in request.goals}
        
        # Track results and completion status
        results: dict[str, GoalResult] = {}
        failed_goal_ids: set[str] = set()
        completed_goal_ids: set[str] = set()
        
        # Build dependency graph
        deps: dict[str, set[str]] = {step.goal_id: set(step.depends_on) for step in plan.steps}
        steps_by_goal: dict[str, PlanStep] = {step.goal_id: step for step in plan.steps}
        
        # Goals that have no unsatisfied dependencies and are ready to run
        ready_goals: set[str] = set(
            goal_id for goal_id, dep_set in deps.items() if not dep_set
        )
        
        # Goals currently running
        running: dict[str, asyncio.Task[GoalResult]] = {}
        
        # All goals that need to be executed
        pending_goals: set[str] = set(deps.keys())
        
        while pending_goals or running:
            # Start as many ready goals as possible (up to concurrency limit)
            concurrency_limit = 1 if self._execution_mode == "sequential" else self._max_concurrent_goals
            while ready_goals and len(running) < concurrency_limit:
                goal_id = ready_goals.pop()
                pending_goals.remove(goal_id)
                
                goal = goals_by_id[goal_id]
                step = steps_by_goal[goal_id]
                
                # Resolve dependency references in inputs for non-synthesis goals
                # Synthesis goals handle dependency injection via _create_synthesis_execution_request
                # We always attempt resolution for non-synthesis goals to catch undeclared references
                if not self._is_synthesis_goal(goal):
                    try:
                        resolved_inputs = self._resolve_dependency_references(
                            goal_id, goal.inputs, deps, results
                        )
                        # Create a modified PlanStep with resolved inputs
                        step = self._create_resolved_execution_request(step, goal, resolved_inputs)
                    except DependencyResolutionError as ex:
                        # Dependency resolution failed - mark goal as failed
                        self._logger.error(
                            "Dependency resolution failed for goal '%s': %s",
                            goal_id, ex
                        )
                        results[goal_id] = GoalResult(
                            goal_id=goal_id,
                            capability_id=goal.capability_id,
                            task_id=None,
                            status=None,
                            failure=ex,
                            depends_on=tuple(step.depends_on),
                        )
                        completed_goal_ids.add(goal_id)
                        failed_goal_ids.add(goal_id)
                        continue
                
                # Check if this is a synthesis goal that needs dependency results
                if self._is_synthesis_goal(goal) and deps[goal_id]:
                    # Build dependency results for injection
                    dep_results = self._build_dependency_results(goal_id, deps, results)
                    
                    # FORENSIC: Log synthesis ready
                    trace_id = get_current_trace_id()
                    if trace_id:
                        dependency_statuses = {}
                        for dep_id in deps[goal_id]:
                            if dep_id in results:
                                if results[dep_id].succeeded:
                                    dependency_statuses[dep_id] = "SUCCESS"
                                elif results[dep_id].skipped:
                                    dependency_statuses[dep_id] = "SKIPPED"
                                else:
                                    dependency_statuses[dep_id] = "FAILED"
                            else:
                                dependency_statuses[dep_id] = "UNKNOWN"
                        
                        all_succeeded = all(s == "SUCCESS" for s in dependency_statuses.values())
                        
                        log_synthesis_ready(
                            trace_id=trace_id,
                            synthesis_goal_id=goal_id,
                            dependency_goal_ids=list(deps[goal_id]),
                            dependency_statuses=dependency_statuses,
                            all_succeeded=all_succeeded,
                        )
                    
                    if dep_results:
                        # Create modified execution request with dependency results
                        step = self._create_synthesis_execution_request(step, goal, dep_results)
                        
                        # FORENSIC: Log exact synthesis input
                        if trace_id:
                            backend_request = step.execution_request.backend_request
                            if hasattr(backend_request, 'messages'):
                                system_messages = [m.content for m in backend_request.messages if m.role == "system"]
                                user_messages = [m.content for m in backend_request.messages if m.role == "user"]
                                message_roles = [m.role for m in backend_request.messages]
                                
                                # Find dependency results message
                                dep_results_msg = None
                                for m in backend_request.messages:
                                    if m.role == "system" and "DEPENDENCY RESULTS" in m.content:
                                        dep_results_msg = m.content
                                        break
                                
                                log_synthesis_input(
                                    trace_id=trace_id,
                                    synthesis_goal_id=goal_id,
                                    model=step.execution_request.target.model.id if step.execution_request.target.model else None,
                                    provider=step.execution_request.target.identifier,
                                    system_messages=system_messages,
                                    dependency_results_message=dep_results_msg,
                                    user_message=user_messages[0] if user_messages else None,
                                    message_roles=message_roles,
                                    message_ordering=message_roles,
                                    advertised_tools=[t.name for t in backend_request.tools] if hasattr(backend_request, 'tools') and backend_request.tools else [],
                                    request_options=asdict(backend_request.options) if hasattr(backend_request, 'options') and backend_request.options else {},
                                    context_metadata={},
                                )
                
                # Create async task for this goal
                coro = self._execute_goal_async(goal, step, progress)
                running[goal_id] = asyncio.create_task(coro)
            
            if not running:
                # No more goals can run (all blocked or done)
                break
                
            # Wait for at least one running goal to complete
            done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
            
            for completed_task in done:
                # Find which goal this task belongs to
                completed_goal_id = None
                for gid, task in running.items():
                    if task is completed_task:
                        completed_goal_id = gid
                        break
                
                if completed_goal_id is None:
                    continue
                    
                del running[completed_goal_id]
                
                try:
                    result = completed_task.result()
                except Exception as ex:
                    # Exception during execution
                    goal = goals_by_id.get(completed_goal_id)
                    capability_id = goal.capability_id if goal else "unknown"
                    result = GoalResult(
                        goal_id=completed_goal_id,
                        capability_id=capability_id,
                        task_id=None,
                        status=None,
                        failure=ex,
                    )
                
                results[completed_goal_id] = result
                completed_goal_ids.add(completed_goal_id)
                
                if not result.succeeded:
                    failed_goal_ids.add(completed_goal_id)
                
                # Check if any dependent goals can now run
                # Collect goals to process to avoid modifying set during iteration
                goals_to_check = list(pending_goals)
                for goal_id in goals_to_check:
                    if goal_id in ready_goals:
                        continue
                    # Check if all dependencies are now satisfied (completed or failed)
                    all_deps_satisfied = True
                    for dep in deps[goal_id]:
                        if dep not in completed_goal_ids:
                            all_deps_satisfied = False
                            break
                    if all_deps_satisfied:
                        # Check if any dependency failed
                        failed_deps = set(deps[goal_id]) & failed_goal_ids
                        if failed_deps:
                            # Dependency failed - check if this is a synthesis goal
                            goal = goals_by_id[goal_id]
                            if self._is_synthesis_goal(goal):
                                # Synthesis goal: execute with dependency results
                                dep_results = self._build_dependency_results(goal_id, deps, results)
                                step = steps_by_goal[goal_id]
                                # Create modified execution request with dependency results
                                synthesis_step = self._create_synthesis_execution_request(step, goal, dep_results)
                                # Execute the synthesis goal with modified request (uses recovery-enabled _execute_goal_async)
                                coro = self._execute_goal_async(goal, synthesis_step, progress)
                                running[goal_id] = asyncio.create_task(coro)
                                pending_goals.remove(goal_id)
                            else:
                                # Regular goal: skip it
                                results[goal_id] = GoalResult(
                                    goal_id=goal_id,
                                    capability_id=goals_by_id[goal_id].capability_id,
                                    task_id=None,
                                    status=None,
                                    skipped=True,
                                    skip_reason=(
                                        "Skipped because dependency/dependencies "
                                        f"failed: {sorted(failed_deps)}."
                                    ),
                                    depends_on=tuple(deps[goal_id]),
                                )
                                failed_goal_ids.add(goal_id)
                                completed_goal_ids.add(goal_id)
                                pending_goals.remove(goal_id)
                        else:
                            ready_goals.add(goal_id)
        
        # Handle any remaining ready goals that were blocked by failures
        final_results: list[GoalResult] = []
        for step in plan.steps:
            goal_id = step.goal_id
            
            if goal_id in results:
                final_results.append(results[goal_id])
            elif goal_id in failed_goal_ids:
                final_results.append(
                    GoalResult(
                        goal_id=goal_id,
                        capability_id=goals_by_id[goal_id].capability_id,
                        task_id=None,
                        status=None,
                        skipped=True,
                        skip_reason=(
                            "Skipped because dependency/dependencies "
                            f"failed: {sorted(set(step.depends_on) & failed_goal_ids)}."
                        ),
                        depends_on=tuple(step.depends_on),
                    )
                )
                failed_goal_ids.add(goal_id)
            else:
                # Should not happen, but handle gracefully
                final_results.append(
                    GoalResult(
                        goal_id=goal_id,
                        capability_id=goals_by_id[goal_id].capability_id,
                        task_id=None,
                        status=None,
                        skipped=True,
                        skip_reason="Execution incomplete",
                        depends_on=tuple(step.depends_on),
                    )
                )
        
        return tuple(final_results)

    def _supervise(
        self,
        request: BrainRequest,
        plan: ExecutionPlan,
        progress: ProgressReporter,
    ) -> tuple[GoalResult, ...]:
        """
        Execute every PlanStep with dependency-aware concurrency.
        
        This is the synchronous entry point that runs the async supervisor.
        """
        return asyncio.run(self._supervise_async(request, plan, progress))

    # ------------------------------------------------------------------
    # Context Engineering (opt-in; never called automatically by
    # handle() -- see docs/architecture/Intelligence_Foundation_Design.md
    # section 7)
    # ------------------------------------------------------------------

    def assemble_context(
        self,
        goal: Goal,
        *,
        budget: TokenBudget | None = None,
        conversation_message_count: int = 0,
    ) -> ContextBundle:
        """
        Assemble a token-budget-aware ContextBundle for `goal`,
        integrating Session, Memory, Knowledge, and Experience (see
        `context_engine/retrieval_ordering.py`'s docstring).

        This is never called automatically by `handle()` -- it is an
        explicit, additive capability a caller (e.g. `chat_capability
        .assemble_context_messages()`, or a future reasoning layer)
        uses before building a Goal's inputs.

        Args:
            goal:
                The (typically preliminary) Goal to assemble context
                for -- reads `goal.inputs["message"]` and
                `goal.metadata["session_id"]`.

            budget:
                Optional `TokenBudget` override. Defaults to the
                `[context_engine]`-configured budget.

            conversation_message_count:
                Number of messages already present in the caller's
                conversation history, purely for the "Searching
                Session" diagnostic log line and
                `ContextBundle.conversation_message_count` -- Context
                Assembly does not re-fetch conversation history itself
                (the caller already holds it).

        Raises:
            ContextEngineUnavailableError:
                If no `memory_manager` was supplied at construction
                time.
        """

        if self._memory_manager is None:
            raise ContextEngineUnavailableError(
                "assemble_context() requires a memory_manager to have "
                "been supplied to Brain's constructor."
            )

        return assemble_context(
            goal=goal,
            memory_manager=self._memory_manager,
            knowledge_manager=self._knowledge_manager,
            experience_source=self._experience_source,
            conversation_message_count=conversation_message_count,
            budget=budget if budget is not None else self._default_budget,
            estimator=self._token_estimator,
            logger=self._logger,
        )

    def compact(
        self,
        messages: "list[ContextMessage] | tuple[ContextMessage, ...]",
        *,
        budget: TokenBudget | None = None,
    ) -> CompactionResult:
        """
        Deterministically compact a conversation history to fit within
        a token budget (see `context_engine/compaction.py`).

        Never called automatically by `handle()`. Never itself calls a
        Provider -- true abstractive summarization is the caller's
        responsibility, built as an explicit Goal through the existing
        `handle()` pipeline.
        """

        return compact(
            messages,
            budget=budget if budget is not None else self._default_budget,
            estimator=self._token_estimator,
        )
