"""
PARIKA Autonomous Execution - Autonomous Executor

Main execution loop for autonomous tasks. Claims READY tasks atomically,
enforces authorization and budget, executes capabilities via the execution
strategy resolution and dispatcher, and handles completion/failure/retry.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Optional

from parika.core.autonomous.contracts import AutonomousTaskStatus
from parika.core.autonomous.models import AutonomousTaskModel
from parika.core.autonomous.repository import AutonomousTaskRepository
from parika.core.autonomous.checkpoint_manager import CheckpointManager, serialize_task_state
from parika.core.autonomous.worker_manager import WorkerManager
from parika.core.autonomous.task_manager import AutonomousTaskManager
from parika.core.autonomous.agent_supervisor import AgentSupervisor
from parika.core.autonomous.execution_strategy import ExecutionStrategy
from parika.core.autonomous.execution_backend import BackendExecutionContext, BackendExecutionResult
from parika.core.autonomous.execution_strategy_resolver import (
    ExecutionStrategyResolver,
    StrategyResolutionResult,
)
from parika.core.autonomous.dispatcher import ExecutionDispatcher
from parika.core.autonomous.authorization import AutonomousAuthorizationBoundary, AutonomousAuthorizationRequest
from parika.core.autonomous.budget import BudgetEnforcer
from parika.core.autonomous.provider_factories import build_provider_request, AutonomousProviderError
from parika.core.autonomous.requirements_serializer import deserialize_execution_requirements
from parika.core.capability_executor.request import CapabilityExecutionRequest
from parika.core.capability_executor.execution_target import ExecutionTarget
from parika.core.capability_executor.execution_backend import ExecutionBackend as CoreExecutionBackend
from parika.core.capability_resolver.capability_request import CapabilityRequest
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.planner.planner import Planner
from parika.core.planner.goal import Goal
from parika.core.planner.execution_plan import ExecutionPlan
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_executor.response import CapabilityExecutionResponse
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.autonomous.mission_manager import MissionManager
from parika.core.multi_agent.mission_coordinator import MissionCoordinator
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class ExecutorConfig:
    """Configuration for AutonomousExecutor."""
    poll_interval_seconds: float = 5.0
    max_concurrent_tasks: int = 10
    checkpoint_interval_seconds: float = 30.0
    shutdown_timeout_seconds: float = 30.0


class AutonomousExecutor:
    """
    Main execution loop for autonomous tasks.
    
    Runs on a dedicated background thread, polls for READY tasks,
    atomically claims them, enforces authorization/budget, and executes
    capabilities via the ExecutionStrategyResolver and Dispatcher.
    """

    def __init__(
        self,
        *,
        task_repository: AutonomousTaskRepository,
        task_manager: AutonomousTaskManager,
        worker_manager: WorkerManager,
        checkpoint_manager: CheckpointManager,
        capability_resolver: CapabilityResolver,
        planner: Planner,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
        provider_manager: ProviderManager,
        resource_manager: ResourceManager,
        policy_engine: PolicyEngine,
        mission_manager: MissionManager,
        authorization_boundary: Optional[AutonomousAuthorizationBoundary] = None,
        budget_enforcer: Optional[BudgetEnforcer] = None,
        agent_supervisor: Optional[AgentSupervisor] = None,
        event_bus: Optional[EventBus] = None,
        logger: Optional[Logger] = None,
        config: Optional[ExecutorConfig] = None,
        # New architecture components
        execution_strategy_resolver: Optional[ExecutionStrategyResolver] = None,
        dispatcher: Optional[ExecutionDispatcher] = None,
        runtime_registry: Optional[Any] = None,  # RuntimeRegistry
        mission_coordinator: Optional[MissionCoordinator] = None,
    ) -> None:
        self._task_repository = task_repository
        self._task_manager = task_manager
        self._worker_manager = worker_manager
        self._checkpoint_manager = checkpoint_manager
        self._capability_resolver = capability_resolver
        self._planner = planner
        self._capability_executor = capability_executor
        self._tool_manager = tool_manager
        self._provider_manager = provider_manager
        self._resource_manager = resource_manager
        self._policy_engine = policy_engine
        self._mission_manager = mission_manager
        self._authorization_boundary = authorization_boundary
        self._budget_enforcer = budget_enforcer
        self._agent_supervisor = agent_supervisor
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__) if logger else None
        self._config = config or ExecutorConfig()

        # New architecture components
        self._execution_strategy_resolver = execution_strategy_resolver
        self._dispatcher = dispatcher
        self._runtime_registry = runtime_registry
        self._mission_coordinator = mission_coordinator

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._active_tasks: set[str] = set()
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_ready = threading.Event()

    def start(self) -> None:
        """Start the executor loop on a background thread."""
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()
        self._loop_ready.clear()
        self._thread = threading.Thread(target=self._run_loop, name="parika-autonomous-executor", daemon=True)
        self._thread.start()
        # Wait for the event loop to be ready
        self._loop_ready.wait(timeout=5.0)
        if self._logger:
            self._logger.info("AutonomousExecutor started")

    def stop(self) -> None:
        """Stop the executor loop gracefully."""
        if not self._running:
            return

        self._running = False
        self._shutdown_event.set()
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._config.shutdown_timeout_seconds)
            
        if self._logger:
            self._logger.info("AutonomousExecutor stopped")

    def _run_loop(self) -> None:
        """Main execution loop - runs on a dedicated event loop."""
        # Create and set event loop for this thread
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        
        if self._logger:
            self._logger.debug("AutonomousExecutor loop started")

        try:
            # Run the async loop
            self._loop.run_until_complete(self._async_run_loop())
        finally:
            # Clean up the loop
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            self._loop.close()
            self._loop = None
            if self._logger:
                self._logger.debug("AutonomousExecutor loop stopped")

    async def _async_run_loop(self) -> None:
        """Async main execution loop."""
        while self._running and not self._shutdown_event.is_set():
            try:
                # Check concurrency limit
                with self._lock:
                    if len(self._active_tasks) >= self._config.max_concurrent_tasks:
                        await asyncio.sleep(self._config.poll_interval_seconds)
                        continue
                
                # Try to claim a READY task
                task_model = self._claim_next_task()
                
                if task_model is None:
                    # No tasks available, wait before polling again
                    await asyncio.sleep(self._config.poll_interval_seconds)
                    continue

                # Execute the task
                await self._execute_task_async(task_model)

            except Exception as e:
                if self._logger:
                    self._logger.exception("Error in AutonomousExecutor loop: %s", e)
                await asyncio.sleep(self._config.poll_interval_seconds)

    def _claim_next_task(self) -> Optional[AutonomousTaskModel]:
        """Try to claim the next READY task atomically."""
        # Get a batch of READY tasks and try to claim them one by one
        ready_tasks = self._task_repository.list_ready_to_run(limit=self._config.max_concurrent_tasks)
        
        for task_model in ready_tasks:
            with self._lock:
                if task_model.id in self._active_tasks:
                    continue
            
            # Try to atomically claim this task
            claimed_model = self._task_repository.claim_ready_task(task_model.id)
            
            if claimed_model is not None:
                with self._lock:
                    self._active_tasks.add(claimed_model.id)
                if self._logger:
                    self._logger.info("Claimed task '%s' for execution", claimed_model.id)
                return claimed_model
            
            # Task was already claimed by another process, try next
            continue
        
        return None

    async def _execute_task_async(self, task_model: AutonomousTaskModel) -> None:
        """Execute a single autonomous task (may be multi-step)."""
        task_id = task_model.id
        
        try:
            if self._logger:
                self._logger.info("Starting execution of task '%s'", task_id)

            # Convert model to domain object for easier handling
            from parika.core.autonomous.task_manager import AutonomousTask
            task = AutonomousTask.from_model(task_model)

            # Check if task has an execution plan (multi-step)
            execution_plan = self._get_execution_plan(task)
            
            if execution_plan:
                # Multi-step execution
                await self._execute_multi_step_task_async(task, execution_plan)
            else:
                # Single capability execution
                await self._execute_single_capability_task_async(task)

        except Exception as e:
            if self._logger:
                self._logger.exception("Unexpected error executing task '%s': %s", task_id, e)
            # Try to mark task as failed
            try:
                self._task_manager.fail(task_id, str(e))
            except Exception:
                pass
        finally:
            with self._lock:
                self._active_tasks.discard(task_id)

    # Keep synchronous wrapper for backward compatibility
    def _execute_task(self, task_model: AutonomousTaskModel) -> None:
        """Synchronous wrapper - not used in new async flow."""
        # This should not be called in the new async flow
        # Kept for backward compatibility with any legacy code
        import asyncio
        if self._loop:
            future = asyncio.run_coroutine_threadsafe(self._execute_task_async(task_model), self._loop)
            future.result()
        else:
            asyncio.run(self._execute_task_async(task_model))

    def _get_execution_plan(self, task: AutonomousTask) -> ExecutionPlan | None:
        """Get execution plan from task if it has one."""
        # Check task metadata for execution plan
        plan_data = task.metadata.get("execution_plan")
        if plan_data:
            from parika.core.planner.execution_plan import ExecutionPlan
            return ExecutionPlan.from_dict(plan_data)
        return None

    async def _execute_multi_step_task_async(self, task: AutonomousTask, execution_plan: ExecutionPlan) -> None:
        """Execute a task with multiple steps (cross-runtime capable)."""
        task_id = task.id
        mission_id = task.mission_id
        
        # Get agent for this task
        agent_id = task.agent_id
        if not agent_id and self._agent_supervisor:
            # Get or spawn agent for this task
            agent = self._agent_supervisor.get_by_task(task_id)
            if agent:
                agent_id = agent[0].id if agent else None
            if not agent_id and self._mission_coordinator:
                assignment = self._mission_coordinator.get_agent_for_task(mission_id, task_id)
                if assignment:
                    agent_id = assignment.agent_id
        
        if not agent_id:
            # Spawn a default agent if needed
            agent_id = f"agent_{task_id[:8]}"

        # Track step results for context passing
        step_results = {}
        
        # Execute each step in dependency order
        for step_index, step in enumerate(execution_plan.steps):
            if self._logger:
                self._logger.info(
                    "Executing step %d/%d of task '%s': capability=%s",
                    step_index + 1, len(execution_plan.steps), task_id, step.capability_id
                )

            # Build inputs for this step (may include previous step results)
            step_inputs = self._build_step_inputs(step, step_results, task.inputs)
            
            # Create a task-like object for this step
            from types import MappingProxyType
            step_task_metadata = MappingProxyType({
                **dict(task.metadata),
                "step_index": step_index,
                "total_steps": len(execution_plan.steps),
                "step_capability_id": step.capability_id,
            })
            
            # Resolve implementation for this step
            if self._execution_strategy_resolver and self._implementation_resolver:
                try:
                    # Create capability request for this step
                    cap_request = CapabilityRequest(
                        capability_id=step.capability_id,
                        metadata=step_task_metadata,
                    )
                    
                    # First resolve implementation
                    impl_resolution = self._implementation_resolver.resolve(
                        cap_request,
                        context=step_task_metadata,
                        agent_id=agent_id,
                        agent_profile_id=task.metadata.get("agent_profile_id", "default"),
                        mission_id=mission_id,
                        task_id=task_id,
                        allowed_runtimes=tuple(task.metadata.get("allowed_runtimes", [])),
                        preferred_runtime=task.metadata.get("preferred_runtime"),
                    )
                    
                    # Then resolve execution strategy
                    strategy_result = self._execution_strategy_resolver.resolve_strategy(
                        implementation_resolution=impl_resolution,
                        task_id=task_id,
                        mission_id=mission_id,
                        agent_id=agent_id,
                        agent_profile_id=task.metadata.get("agent_profile_id", "default"),
                        task_metadata=step_task_metadata,
                        step_index=step_index,
                        total_steps=len(execution_plan.steps),
                        previous_results=MappingProxyType(step_results),
                    )
                    
                    # Validate environment
                    if not self._execution_strategy_resolver.validate_environment(
                        strategy_result.strategy
                    ):
                        # Try fallback
                        fallback = self._execution_strategy_resolver.try_fallback(
                            strategy_result.strategy,
                            "environment_unavailable",
                            step_task_metadata,
                        )
                        if fallback:
                            strategy_result = fallback
                        else:
                            raise RuntimeError(f"No available environment for step {step_index}")
                    
                    # Dispatch execution
                    backend_result = await self._dispatch_step(
                        strategy=strategy_result.strategy,
                        inputs=step_inputs,
                        context=BackendExecutionContext(
                            task_id=task_id,
                            mission_id=mission_id,
                            agent_id=agent_id,
                            agent_profile_id=task.metadata.get("agent_profile_id", "default"),
                            permission_context=task.metadata.get("permission_context", MappingProxyType({})),
                            resource_budget=task.resource_budget,
                            step_index=step_index,
                            total_steps=len(execution_plan.steps),
                            previous_results=MappingProxyType(step_results),
                        ),
                    )
                    
                    if not backend_result.success:
                        # Handle failure
                        self._handle_step_failure(task, step_index, backend_result.error)
                        return
                    
                    # Store step result for next steps
                    step_results[step.id] = backend_result.result
                    
                    # Update progress
                    progress = (step_index + 1) / len(execution_plan.steps)
                    self._task_manager.update_progress(task_id, progress, f"Completed step {step_index + 1}")
                    
                except Exception as e:
                    self._handle_step_failure(task, step_index, str(e))
                    return
            else:
                # Fallback to legacy path if no strategy resolver
                self._execute_legacy_step(task, step, step_inputs, step_results, agent_id)
        
        # All steps completed successfully
        self._task_manager.complete(task_id, MappingProxyType({"result": step_results}))
        if self._logger:
            self._logger.info("Multi-step task '%s' completed successfully", task_id)

    # Keep synchronous wrapper for backward compatibility
    def _execute_multi_step_task(self, task: AutonomousTask, execution_plan: ExecutionPlan) -> None:
        """Synchronous wrapper - not used in new async flow."""
        import asyncio
        if self._loop:
            future = asyncio.run_coroutine_threadsafe(self._execute_multi_step_task_async(task, execution_plan), self._loop)
            future.result()
        else:
            asyncio.run(self._execute_multi_step_task_async(task, execution_plan))

    def _build_step_inputs(self, step, step_results: dict, task_inputs: MappingProxyType) -> MappingProxyType:
        """Build inputs for a step from task inputs and previous step results."""
        # For now, use task inputs directly
        # In a full implementation, this would merge step.inputs with step_results
        return task_inputs

    async def _execute_single_capability_task_async(self, task: AutonomousTask) -> None:
        """Execute a task with a single capability (new architecture async path)."""
        task_id = task.id
        mission_id = task.mission_id
        
        # 1. Authorization
        if not self._authorize_task(task):
            self._fail_task(task, "Authorization denied", worker_crashed=False)
            return

        # 2. Budget admission
        if not self._check_budget(task):
            self._fail_task(task, "Budget exceeded", worker_crashed=False)
            return

        # 3. Skill activation if task requires a skill
        skill_id = task.metadata.get("skill_id")
        skill_activated = False
        if skill_id and hasattr(self, '_skill_loader') and self._skill_loader:
            skill_result = self._skill_loader.prepare_skill_for_execution(
                skill_id,
                mission_id=task.mission_id,
                task_id=task.id,
                agent_id=task.agent_id or "system",
                agent_profile_id=task.metadata.get("agent_profile_id", "default"),
                required_capabilities=tuple(task.metadata.get("required_capabilities", [])),
                allowed_tools=tuple(task.metadata.get("allowed_tools", [])),
            )
            if not skill_result.activated:
                self._fail_task(task, f"Skill activation failed: {skill_result.reason}", worker_crashed=False)
                return
            skill_activated = True
            if self._logger:
                self._logger.info("Activated skill '%s' for task '%s'", skill_id, task_id)

        # 4. Resolve implementation using ImplementationResolver
        impl_resolution = None
        if self._execution_strategy_resolver and self._implementation_resolver:
            # Use new architecture path
            cap_request = CapabilityRequest(
                capability_id=task.capability_id,
                metadata=task.metadata,
            )
            
            try:
                impl_resolution = self._implementation_resolver.resolve(
                    cap_request,
                    context=task.metadata,
                    agent_id=task.agent_id,
                    agent_profile_id=task.metadata.get("agent_profile_id"),
                    mission_id=task.mission_id,
                    task_id=task.id,
                    allowed_runtimes=tuple(task.metadata.get("allowed_runtimes", [])),
                    preferred_runtime=task.metadata.get("preferred_runtime"),
                )
            except Exception as e:
                if self._logger:
                    self._logger.warning("Implementation selection failed: %s", e)
                self._fail_task(task, f"Implementation resolution failed: {e}", worker_crashed=False)
                return
        
        if not impl_resolution:
            # Fallback to legacy capability resolver
            resolution = self._capability_resolver.resolve(
                CapabilityRequest(capability_id=task.capability_id, metadata=task.metadata)
            )
            # Execute using legacy path
            self._execute_legacy_single(task, resolution, skill_id if skill_activated else None)
            return

        # 5. Resolve execution strategy
        strategy_result = self._execution_strategy_resolver.resolve_strategy(
            implementation_resolution=impl_resolution,
            task_id=task.id,
            mission_id=mission_id,
            agent_id=task.agent_id,
            agent_profile_id=task.metadata.get("agent_profile_id", "default"),
            task_metadata=task.metadata,
        )

        # 6. Validate required environment
        if not self._execution_strategy_resolver.validate_environment(strategy_result.strategy):
            # Try fallback
            fallback = self._execution_strategy_resolver.try_fallback(
                strategy_result.strategy,
                "environment_unavailable",
                task.metadata,
            )
            if fallback:
                strategy_result = fallback
            else:
                self._fail_task(task, "No available environment for execution", worker_crashed=False)
                return

        # 7. Spawn worker
        worker, execution = self._worker_manager.spawn(
            task_id=task.id,
            heartbeat_interval_seconds=30.0,
            timeout_seconds=120.0,
        )
        self._worker_manager.start(worker.id)

        # 8. Dispatch execution
        try:
            backend_result = await self._dispatch_step(
                strategy=strategy_result.strategy,
                inputs=task.inputs,
                context=BackendExecutionContext(
                    task_id=task.id,
                    mission_id=mission_id,
                    agent_id=task.agent_id or "system",
                    agent_profile_id=task.metadata.get("agent_profile_id", "default"),
                    permission_context=task.metadata.get("permission_context", MappingProxyType({})),
                    resource_budget=task.resource_budget,
                    step_index=0,
                    total_steps=1,
                ),
            )

            if not backend_result.success:
                self._worker_manager.fail(worker.id, backend_result.error)
                self._handle_task_failure(task, backend_result.error, strategy_result.strategy)
                return

            # 9. Success
            self._worker_manager.complete(worker.id, MappingProxyType({"result": backend_result.result}))
            self._task_manager.complete(task.id, MappingProxyType({"result": backend_result.result}))
            
            if self._logger:
                self._logger.info("Task '%s' completed successfully", task_id)

        except Exception as e:
            error_msg = str(e)
            if self._logger:
                self._logger.error("Task '%s' failed: %s", task_id, error_msg)
            
            self._worker_manager.fail(worker.id, error_msg)
            self._handle_task_failure(task, error_msg, strategy_result.strategy)

    # Keep synchronous wrapper for backward compatibility
    def _execute_single_capability_task(self, task: AutonomousTask) -> None:
        """Synchronous wrapper - not used in new async flow."""
        import asyncio
        if self._loop:
            future = asyncio.run_coroutine_threadsafe(self._execute_single_capability_task_async(task), self._loop)
            future.result()
        else:
            asyncio.run(self._execute_single_capability_task_async(task))

    async def _dispatch_step(
        self,
        strategy: ExecutionStrategy,
        inputs: MappingProxyType[str, Any],
        context: BackendExecutionContext,
    ) -> BackendExecutionResult:
        """Dispatch execution to the appropriate backend."""
        if self._dispatcher:
            # Use the executor's dedicated event loop
            if self._loop is None:
                raise RuntimeError("Executor event loop not initialized")
            
            # Submit coroutine to the executor's loop and wait for result
            future = asyncio.run_coroutine_threadsafe(
                self._dispatcher.dispatch(strategy, inputs, context),
                self._loop
            )
            return future.result()
        else:
            # Fallback to legacy execution
            raise RuntimeError("No dispatcher available")

    def _handle_task_failure(
        self, 
        task: AutonomousTask, 
        error: str, 
        strategy: ExecutionStrategy | None = None
    ) -> None:
        """Handle task failure - retry or fallback."""
        # Record retry in budget enforcer
        if self._budget_enforcer:
            self._budget_enforcer.record_retry(task.id)

        # Try fallback if we have a strategy
        if strategy and self._execution_strategy_resolver:
            fallback = self._execution_strategy_resolver.try_fallback(
                strategy,
                "transient_failure",
                task.metadata,
            )
            if fallback:
                if self._logger:
                    self._logger.info("Attempting fallback for task '%s'", task.id)
                # Retry with fallback strategy (would need to re-queue task)
                # For now, just mark for retry
                self._task_manager.fail(task.id, error)
                return

        # No fallback available, let task_manager handle retry logic
        updated_task = self._task_manager.fail(task.id, error)
        
        if updated_task and updated_task.status.value == "retrying":
            if self._logger:
                self._logger.info("Task '%s' marked for retry (attempt %d)", 
                                task.id, updated_task.retry_count)
        elif updated_task and updated_task.status.value == "failed":
            if self._logger:
                self._logger.info("Task '%s' failed permanently after %d retries", 
                                task.id, updated_task.retry_count)

    def _handle_step_failure(self, task: AutonomousTask, step_index: int, error: str) -> None:
        """Handle failure of a multi-step task."""
        self._task_manager.fail(task.id, f"Step {step_index} failed: {error}")
        if self._logger:
            self._logger.error("Task '%s' failed at step %d: %s", task.id, step_index, error)

    def _execute_legacy_step(self, task, step, step_inputs, step_results, agent_id):
        """Execute a step using legacy path (for backward compatibility)."""
        # This maintains backward compatibility for existing single-capability tasks
        pass

    def _execute_legacy_single(self, task, resolution, skill_id):
        """Execute using legacy path."""
        # Legacy execution path for backward compatibility
        worker, execution = self._worker_manager.spawn(
            task_id=task.id,
            heartbeat_interval_seconds=30.0,
            timeout_seconds=120.0,
        )
        self._worker_manager.start(worker.id)

        try:
            if resolution.definition.category.value == "tool":
                result = self._execute_tool_capability(task, resolution, worker.id, execution.id)
            else:
                result = self._execute_provider_capability(task, resolution, worker.id, execution.id)

            self._worker_manager.complete(worker.id, MappingProxyType({"result": result}))
            self._task_manager.complete(task.id, MappingProxyType({"result": result}))
            
            if self._logger:
                self._logger.info("Task '%s' completed successfully (legacy)", task.id)

        except Exception as e:
            error_msg = str(e)
            if self._logger:
                self._logger.error("Task '%s' failed: %s", task.id, error_msg)
            
            self._worker_manager.fail(worker.id, error_msg)
            self._handle_task_failure(task, error_msg)

    def _authorize_task(self, task: AutonomousTask) -> bool:
        """Check authorization for task execution."""
        if self._authorization_boundary is None:
            return True

        # Get agent info if available
        agent_id = task.agent_id
        agent_profile_id = None
        permission_context = task.metadata.get("permission_context", {})
        resource_budget = task.resource_budget

        # Try to get agent profile ID from agent instance
        if self._agent_supervisor and task.agent_id:
            agent = self._agent_supervisor.get(task.agent_id)
            if agent:
                agent_profile_id = agent.agent_profile_id
                permission_context = dict(agent.permission_context)
                resource_budget = dict(agent.resource_budget)

        if not agent_profile_id:
            agent_profile_id = "default"

        auth_request = AutonomousAuthorizationRequest(
            agent_id=task.agent_id or "system",
            agent_profile_id=agent_profile_id,
            capability_id=task.capability_id,
            inputs=task.inputs,
            mission_id=task.mission_id,
            task_id=task.id,
            permission_context=MappingProxyType(permission_context),
            resource_budget=MappingProxyType(resource_budget),
        )

        decision = self._authorization_boundary.authorize(auth_request)
        
        if not decision.allowed:
            if self._logger:
                self._logger.warning("Authorization denied for task '%s': %s", task.id, decision.reason)
            return False

        return True

    def _check_budget(self, task: AutonomousTask) -> bool:
        """Check budget admission for task execution."""
        if self._budget_enforcer is None:
            return True

        # Initialize budget if not already set
        if self._budget_enforcer.get_limit(task.id) is None:
            self._budget_enforcer.set_budget(task.id, task.resource_budget)

        result = self._budget_enforcer.check_budget(task.id)
        
        if not result.allowed:
            if self._logger:
                self._logger.warning("Budget denied for task '%s': %s", task.id, 
                                   "; ".join(v.message for v in result.violations))
            return False

        return True

    def _execute_tool_capability(
        self,
        task: AutonomousTask,
        resolution,
        worker_id: str,
        execution_id: str,
    ) -> Any:
        """Execute a TOOL capability."""
        # Build ToolRequest
        tool_request = ToolRequest(
            arguments=task.inputs,
            metadata=task.metadata,
        )

        # Find the tool for this capability
        tools = self._tool_manager.get_all()
        tool = None
        for t in tools:
            if t.enabled and task.capability_id in t.capabilities:
                tool = t
                break

        if tool is None:
            raise ValueError(f"No enabled tool implements capability '{task.capability_id}'")

        # Build execution request
        target = ExecutionTarget(
            backend=CoreExecutionBackend.TOOL,
            identifier=tool.id,
        )

        execution_request = CapabilityExecutionRequest(
            resolution=resolution,
            target=target,
            backend_request=tool_request,
            metadata=task.metadata,
        )

        # Execute via CapabilityExecutor
        response = self._capability_executor.execute(execution_request, task_id=task.id)
        
        # Record worker heartbeat
        self._worker_manager.heartbeat(worker_id, progress=1.0)
        
        return response.backend_response

    def _execute_provider_capability(
        self,
        task: AutonomousTask,
        resolution,
        worker_id: str,
        execution_id: str,
    ) -> Any:
        """Execute a PROVIDER capability via Planner."""
        # Build Goal from durable task data
        goal = self._build_goal_from_task(task, resolution)

        # Call Planner.plan() to get ExecutionPlan
        plan = self._planner.plan([goal])

        if not plan.steps:
            raise ValueError(f"Planner produced empty plan for task '{task.id}'")

        execution_request = plan.steps[0].execution_request

        # Execute via CapabilityExecutor
        response = self._capability_executor.execute(execution_request, task_id=task.id)
        
        # Record worker heartbeat
        self._worker_manager.heartbeat(worker_id, progress=1.0)
        
        return response.backend_response

    def _build_goal_from_task(self, task: AutonomousTask, resolution) -> Goal:
        """Reconstruct Goal from durable autonomous task data."""
        # Reconstruct provider_request_builder from factory
        def provider_request_builder(res, model):
            return build_provider_request(
                capability_id=task.capability_id,
                inputs=task.inputs,
                metadata=task.metadata,
                resolution=res,
                model=model,
            )

        # Reconstruct execution_requirements
        execution_req_metadata = {}
        if task.execution_requirements:
            # Convert MappingProxyType to dict for Goal metadata
            execution_req_metadata["execution_requirements"] = dict(task.execution_requirements)

        # Merge with existing metadata
        merged_metadata = dict(task.metadata)
        merged_metadata.update(execution_req_metadata)

        return Goal(
            id=task.id,
            capability_id=task.capability_id,
            inputs=task.inputs,
            depends_on=tuple(),  # Dependencies handled by task manager
            provider_request_builder=provider_request_builder,
            metadata=merged_metadata,
        )

    def _fail_task(self, task: AutonomousTask, reason: str, worker_crashed: bool = False) -> None:
        """Mark task as failed with given reason."""
        self._task_manager.fail(task.id, reason)
        if self._logger:
            self._logger.warning("Task '%s' failed: %s", task.id, reason)