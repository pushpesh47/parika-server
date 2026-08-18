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

from typing import TYPE_CHECKING
import asyncio

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.planner.execution_plan import ExecutionPlan
from parika.core.planner.goal import Goal
from parika.core.planner.plan_step import PlanStep
from parika.core.planner.planner import Planner
from parika.core.task_manager.request import TaskRequest
from parika.core.task_manager.task_manager import TaskManager
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

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

if TYPE_CHECKING:
    from parika.core.agent_orchestrator.agent_orchestrator import AgentOrchestrator
    from parika.core.configuration.configuration import Configuration
    from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
    from parika.core.memory_manager.memory_manager import MemoryManager
    from parika.core.planner.model_selection.experience_source import ExperienceSource

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
        self._max_concurrent_goals = configuration.get("concurrency.max_concurrent_goals", 4) if configuration is not None else 4

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
        )

        self._logger.debug(
            "Brain completed request '%s' (succeeded=%s).",
            request.id,
            response.succeeded,
        )

        progress.completed(
            message=f"succeeded={response.succeeded}",
            succeeded=response.succeeded,
        )

        return response

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
        rather than raised.
        """

        task = self._task_manager.create(
            TaskRequest(
                capability_id=goal.capability_id,
                inputs=goal.inputs,
                context_id=goal.context_id,
                metadata=goal.metadata,
            ),
        )

        goal_progress = progress.child(EXECUTE_GOAL_SOURCE_ID, task_id=task.id)
        goal_progress.started(message=f"Executing goal '{goal.id}'.")

        try:
            # Run synchronous execute in thread pool to avoid blocking event loop
            executed_task = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._task_manager.execute(task.id, step.execution_request),
            )

        except Exception as ex:
            self._logger.exception(
                "Execution failed for goal '%s' (task '%s').",
                goal.id,
                task.id,
            )

            goal_progress.failed(message=str(ex))

            return GoalResult(
                goal_id=goal.id,
                task_id=task.id,
                status=self._task_manager.get(task.id).status,
                failure=ex,
            )

        goal_progress.completed()

        return GoalResult(
            goal_id=goal.id,
            task_id=executed_task.id,
            status=executed_task.status,
            response=executed_task.response,
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
            while ready_goals and len(running) < self._max_concurrent_goals:
                goal_id = ready_goals.pop()
                pending_goals.remove(goal_id)
                
                goal = goals_by_id[goal_id]
                step = steps_by_goal[goal_id]
                
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
                    result = GoalResult(
                        goal_id=completed_goal_id,
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
                    # Check if all dependencies are now satisfied
                    all_deps_satisfied = True
                    for dep in deps[goal_id]:
                        if dep not in completed_goal_ids:
                            all_deps_satisfied = False
                            break
                    if all_deps_satisfied:
                        # Check if any dependency failed
                        if any(dep in failed_goal_ids for dep in deps[goal_id]):
                            # Dependency failed - skip this goal
                            results[goal_id] = GoalResult(
                                goal_id=goal_id,
                                task_id=None,
                                status=None,
                                skipped=True,
                                skip_reason=(
                                    "Skipped because dependency/dependencies "
                                    f"failed: {sorted(set(deps[goal_id]) & failed_goal_ids)}."
                                ),
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
                        task_id=None,
                        status=None,
                        skipped=True,
                        skip_reason=(
                            "Skipped because dependency/dependencies "
                            f"failed: {sorted(set(step.depends_on) & failed_goal_ids)}."
                        ),
                    )
                )
                failed_goal_ids.add(goal_id)
            else:
                # Should not happen, but handle gracefully
                final_results.append(
                    GoalResult(
                        goal_id=goal_id,
                        task_id=None,
                        status=None,
                        skipped=True,
                        skip_reason="Execution incomplete",
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
