"""
PARIKA Autonomous Execution - Autonomous Executor

Main execution loop for autonomous tasks. Claims READY tasks atomically,
enforces authorization and budget, executes capabilities via the existing
PARIKA Core execution path, and handles completion/failure/retry.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Optional

from parika.core.autonomous.contracts import AutonomousTaskStatus
from parika.core.autonomous.models import AutonomousTaskModel
from parika.core.autonomous.provider_factories import build_provider_request, AutonomousProviderError
from parika.core.autonomous.requirements_serializer import deserialize_execution_requirements
from parika.core.capability_executor.request import CapabilityExecutionRequest
from parika.core.capability_executor.execution_backend import ExecutionBackend
from parika.core.capability_executor.execution_target import ExecutionTarget
from parika.core.capability_resolver.capability_request import CapabilityRequest
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.planner.planner import Planner
from parika.core.planner.goal import Goal
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_executor.response import CapabilityExecutionResponse
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.autonomous.authorization import AutonomousAuthorizationBoundary, AutonomousAuthorizationRequest
from parika.core.autonomous.budget import BudgetEnforcer
from parika.core.autonomous.repository import AutonomousTaskRepository
from parika.core.autonomous.checkpoint_manager import CheckpointManager, serialize_task_state
from parika.core.autonomous.worker_manager import WorkerManager
from parika.core.autonomous.task_manager import AutonomousTaskManager
from parika.core.autonomous.agent_supervisor import AgentSupervisor
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

# Phase 2 imports - use TYPE_CHECKING to avoid circular imports
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parika.core.skill_system.skill_loader import SkillLoader
    from parika.core.skill_system.skill_catalog import SkillCatalog
    from parika.core.implementation_registry.implementation_resolver import ImplementationResolver
    from parika.core.agent_runtime.runtime_registry import RuntimeRegistry
    from parika.core.multi_agent.mission_coordinator import MissionCoordinator
    from parika.core.autonomous_waiting.wait_manager import WaitManager
    from parika.core.agent_communication.message_bus import MessageBus
else:
    SkillLoader = Any
    SkillCatalog = Any
    ImplementationResolver = Any
    RuntimeRegistry = Any
    MissionCoordinator = Any
    WaitManager = Any
    MessageBus = Any


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
    capabilities via the existing PARIKA Core execution path.
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
        authorization_boundary: Optional["AutonomousAuthorizationBoundary"] = None,
        budget_enforcer: Optional[BudgetEnforcer] = None,
        agent_supervisor: Optional["AgentSupervisor"] = None,
        event_bus: Optional[EventBus] = None,
        logger: Optional[Logger] = None,
        config: Optional[ExecutorConfig] = None,
        # Phase 2 services
        skill_loader: Optional[SkillLoader] = None,
        skill_catalog: Optional[SkillCatalog] = None,
        implementation_resolver: Optional[ImplementationResolver] = None,
        runtime_registry: Optional[RuntimeRegistry] = None,
        mission_coordinator: Optional[MissionCoordinator] = None,
        wait_manager: Optional[WaitManager] = None,
        message_bus: Optional[MessageBus] = None,
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
        self._authorization_boundary = authorization_boundary
        self._budget_enforcer = budget_enforcer
        self._agent_supervisor = agent_supervisor
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__) if logger else None
        self._config = config or ExecutorConfig()

        # Phase 2 services
        self._skill_loader = skill_loader
        self._skill_catalog = skill_catalog
        self._implementation_resolver = implementation_resolver
        self._runtime_registry = runtime_registry
        self._mission_coordinator = mission_coordinator
        self._wait_manager = wait_manager
        self._message_bus = message_bus

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._active_tasks: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the executor loop on a background thread."""
        if self._running:
            return

        self._running = True
        self._shutdown_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="parika-autonomous-executor", daemon=True)
        self._thread.start()
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
        """Main execution loop."""
        if self._logger:
            self._logger.debug("AutonomousExecutor loop started")

        while self._running and not self._shutdown_event.is_set():
            try:
                # Check concurrency limit
                with self._lock:
                    if len(self._active_tasks) >= self._config.max_concurrent_tasks:
                        time.sleep(self._config.poll_interval_seconds)
                        continue
                
                # Try to claim a READY task
                task_model = self._claim_next_task()
                
                if task_model is None:
                    # No tasks available, wait before polling again
                    time.sleep(self._config.poll_interval_seconds)
                    continue

                # Execute the task
                self._execute_task(task_model)

            except Exception as e:
                if self._logger:
                    self._logger.exception("Error in AutonomousExecutor loop: %s", e)
                time.sleep(self._config.poll_interval_seconds)

        if self._logger:
            self._logger.debug("AutonomousExecutor loop stopped")

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

    def _execute_task(self, task_model: AutonomousTaskModel) -> None:
        """Execute a single autonomous task."""
        task_id = task_model.id
        
        try:
            if self._logger:
                self._logger.info("Starting execution of task '%s'", task_id)

            # Convert model to domain object for easier handling
            from parika.core.autonomous.task_manager import AutonomousTask
            task = AutonomousTask.from_model(task_model)

            # 1. Authorization
            if not self._authorize_task(task):
                self._fail_task(task, "Authorization denied", worker_crashed=False)
                return

            # 2. Budget admission
            if not self._check_budget(task):
                self._fail_task(task, "Budget exceeded", worker_crashed=False)
                return

            # 3. Phase 2: Skill activation if task requires a skill
            skill_id = task.metadata.get("skill_id")
            skill_activated = False
            if skill_id and self._skill_loader:
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

            # 4. Resolve capability - use ImplementationResolver if available for dynamic selection
            if self._implementation_resolver:
                # Use dynamic implementation selection
                try:
                    impl_resolution = self._implementation_resolver.resolve(
                        CapabilityRequest(capability_id=task.capability_id, metadata=task.metadata),
                        context=task.metadata,
                        agent_id=task.agent_id,
                        agent_profile_id=task.metadata.get("agent_profile_id"),
                        mission_id=task.mission_id,
                        task_id=task.id,
                        allowed_runtimes=tuple(task.metadata.get("allowed_runtimes", [])),
                        preferred_runtime=task.metadata.get("preferred_runtime"),
                    )
                    # Use the selected implementation's capability_id
                    capability_id = impl_resolution.implementation.capability_id
                    resolution = impl_resolution.capability_resolution
                except Exception as e:
                    if self._logger:
                        self._logger.warning("Implementation selection failed, falling back to capability resolver: %s", e)
                    resolution = self._capability_resolver.resolve(
                        CapabilityRequest(capability_id=task.capability_id, metadata=task.metadata)
                    )
            else:
                resolution = self._capability_resolver.resolve(
                    CapabilityRequest(capability_id=task.capability_id, metadata=task.metadata)
                )

            # 5. Phase 2: Runtime selection if available
            selected_runtime = None
            if self._runtime_registry:
                # Determine preferred runtime from task metadata or implementation
                preferred_runtime = task.metadata.get("preferred_runtime")
                allowed_runtimes = tuple(task.metadata.get("allowed_runtimes", []))
                
                # Get available runtimes
                available_runtimes = self._runtime_registry.list_runtimes(status="running")
                if available_runtimes:
                    # Filter by allowed runtimes
                    if allowed_runtimes:
                        available_runtimes = [r for r in available_runtimes if r.runtime_type.value in allowed_runtimes]
                    # Prefer specified runtime
                    if preferred_runtime:
                        preferred = [r for r in available_runtimes if r.runtime_type.value == preferred_runtime]
                        if preferred:
                            selected_runtime = preferred[0]
                    if not selected_runtime and available_runtimes:
                        selected_runtime = available_runtimes[0]
                    
                    if selected_runtime:
                        if self._logger:
                            self._logger.info("Selected runtime '%s' (%s) for task '%s'", 
                                            selected_runtime.name, selected_runtime.runtime_type.value, task_id)

            # 6. Spawn worker and execution
            worker, execution = self._worker_manager.spawn(
                task_id=task.id,
                heartbeat_interval_seconds=30.0,
                timeout_seconds=120.0,
            )

            self._worker_manager.start(worker.id)

            try:
                # 7. Execute capability - use runtime if available
                if selected_runtime and selected_runtime.runtime_type.value != "native":
                    # Use selected runtime (e.g., Hermes)
                    result = self._execute_via_runtime(
                        task=task,
                        resolution=resolution,
                        worker_id=worker.id,
                        execution_id=execution.id,
                        runtime=selected_runtime,
                        skill_id=skill_id if skill_activated else None,
                    )
                elif resolution.definition.category.value == "tool":
                    result = self._execute_tool_capability(task, resolution, worker.id, execution.id)
                else:
                    result = self._execute_provider_capability(task, resolution, worker.id, execution.id)

                # 8. Success
                self._worker_manager.complete(worker.id, MappingProxyType({"result": result}))
                self._task_manager.complete(task.id, MappingProxyType({"result": result}))
                
                if self._logger:
                    self._logger.info("Task '%s' completed successfully", task_id)

            except Exception as e:
                # Failure handling
                error_msg = str(e)
                if self._logger:
                    self._logger.error("Task '%s' failed: %s", task_id, error_msg)
                
                self._worker_manager.fail(worker.id, error_msg)
                self._handle_task_failure(task, error_msg)

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

    def _authorize_task(self, task: "AutonomousTask") -> bool:
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

    def _check_budget(self, task: "AutonomousTask") -> bool:
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
        task: "AutonomousTask",
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
            backend=ExecutionBackend.TOOL,
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
        task: "AutonomousTask",
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

    def _execute_via_runtime(
        self,
        task: "AutonomousTask",
        resolution,
        worker_id: str,
        execution_id: str,
        runtime,
        skill_id: str | None = None,
    ) -> Any:
        """Execute a capability via a selected runtime (e.g., Hermes)."""
        if self._logger:
            self._logger.info("Executing task '%s' via runtime '%s'", task.id, runtime.runtime_id)
        
        # Build execution context
        context = MappingProxyType({
            "mission_id": task.mission_id,
            "task_id": task.id,
            "agent_id": task.agent_id or "system",
            "agent_profile_id": task.metadata.get("agent_profile_id", "default"),
            "permission_context": task.metadata.get("permission_context", MappingProxyType({})),
            "resource_budget": task.resource_budget,
            "timeout_seconds": task.metadata.get("timeout_seconds", 300.0),
        })
        
        # Execute via runtime
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Build inputs for runtime
        inputs = MappingProxyType(dict(task.inputs))
        
        # Run async execution
        result = loop.run_until_complete(runtime.execute(
            agent_id=task.agent_id or "system",
            task_id=task.id,
            capability_id=resolution.definition.id,
            inputs=inputs,
            context=context,
            skill_id=skill_id,
        ))
        
        # Record worker heartbeat
        self._worker_manager.heartbeat(worker_id, progress=1.0)
        
        return dict(result)

    def _build_goal_from_task(self, task: "AutonomousTask", resolution) -> Goal:
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

    def _handle_task_failure(self, task: "AutonomousTask", error: str) -> None:
        """Handle task failure - retry or mark failed."""
        # Record retry in budget enforcer
        if self._budget_enforcer:
            self._budget_enforcer.record_retry(task.id)

        # Let task_manager handle retry logic
        updated_task = self._task_manager.fail(task.id, error)
        
        if updated_task and updated_task.status.value == "retrying":
            # Task will be retried - it will go through READY again
            if self._logger:
                self._logger.info("Task '%s' marked for retry (attempt %d)", 
                                task.id, updated_task.retry_count)
        elif updated_task and updated_task.status.value == "failed":
            if self._logger:
                self._logger.info("Task '%s' failed permanently after %d retries", 
                                task.id, updated_task.retry_count)
            
            # Phase 2: Try fallback implementation if available
            if self._implementation_resolver and self._runtime_registry:
                self._try_fallback_execution(task, error)

    def _try_fallback_execution(self, task: "AutonomousTask", error: str) -> None:
        """Try to execute task with fallback implementation/runtime."""
        if self._logger:
            self._logger.info("Attempting fallback for task '%s'", task.id)
        
        # This would require the task to be re-queued with a different implementation
        # For now, just log the attempt
        pass

    def _fail_task(self, task: "AutonomousTask", reason: str, worker_crashed: bool = False) -> None:
        """Mark task as failed with given reason."""
        self._task_manager.fail(task.id, reason)
        if self._logger:
            self._logger.warning("Task '%s' failed: %s", task.id, reason)