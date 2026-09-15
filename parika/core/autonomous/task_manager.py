"""
PARIKA Autonomous Execution - Autonomous Task Manager

Manages the lifecycle of autonomous tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.contracts import AutonomousTaskStatus, validate_task_transition
from parika.core.autonomous.events import (
    TaskCreatedEvent,
    TaskStartedEvent,
    TaskProgressEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskCancelledEvent,
    TaskPausedEvent,
    TaskResumedEvent,
    TaskWaitingForDependencyEvent,
)
from parika.core.autonomous.models import AutonomousTaskModel
from parika.core.autonomous.repository import AutonomousTaskRepository, TaskDependencyRepository
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class AutonomousTask:
    """Autonomous Task domain model."""
    id: str
    mission_id: str
    parent_task_id: str | None
    agent_id: str | None
    name: str
    description: str
    capability_id: str | None
    inputs: MappingProxyType[str, Any]
    status: AutonomousTaskStatus
    priority: int
    progress: float
    created_at: datetime
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    deadline: datetime | None
    max_retries: int
    retry_count: int
    resource_budget: MappingProxyType[str, Any]
    checkpoint_id: str | None
    result: MappingProxyType[str, Any] | None
    failure: str | None
    metadata: MappingProxyType[str, Any]
    provider_request_type: str | None
    task_category: str | None
    execution_requirements: MappingProxyType[str, Any] | None
    execution_plan: Any | None = None  # Optional ExecutionPlan for multi-step tasks

    @classmethod
    def from_model(cls, model: AutonomousTaskModel) -> "AutonomousTask":
        execution_plan = None
        if model.execution_plan:
            from parika.core.planner.execution_plan import ExecutionPlan
            execution_plan = ExecutionPlan.from_dict(model.execution_plan)
        
        return cls(
            id=model.id,
            mission_id=model.mission_id,
            parent_task_id=model.parent_task_id,
            agent_id=model.agent_id,
            name=model.name,
            description=model.description,
            capability_id=model.capability_id,
            inputs=MappingProxyType(model.inputs),
            status=AutonomousTaskStatus(model.status),
            priority=model.priority,
            progress=model.progress,
            created_at=model.created_at,
            started_at=model.started_at,
            updated_at=model.updated_at,
            completed_at=model.completed_at,
            deadline=model.deadline,
            max_retries=model.max_retries,
            retry_count=model.retry_count,
            resource_budget=MappingProxyType(model.resource_budget),
            checkpoint_id=model.checkpoint_id,
            result=MappingProxyType(model.result) if model.result else None,
            failure=model.failure,
            metadata=MappingProxyType(model.task_metadata),
            provider_request_type=model.provider_request_type,
            task_category=model.task_category,
            execution_requirements=MappingProxyType(model.execution_requirements) if model.execution_requirements else None,
            execution_plan=execution_plan,
        )

    def to_model(self) -> AutonomousTaskModel:
        execution_plan_dict = None
        if self.execution_plan:
            execution_plan_dict = self.execution_plan.to_dict()
        
        return AutonomousTaskModel(
            id=self.id,
            mission_id=self.mission_id,
            parent_task_id=self.parent_task_id,
            agent_id=self.agent_id,
            name=self.name,
            description=self.description,
            capability_id=self.capability_id,
            inputs=dict(self.inputs),
            status=self.status.value,
            priority=self.priority,
            progress=self.progress,
            created_at=self.created_at,
            started_at=self.started_at,
            updated_at=self.updated_at,
            completed_at=self.completed_at,
            deadline=self.deadline,
            max_retries=self.max_retries,
            retry_count=self.retry_count,
            resource_budget=dict(self.resource_budget),
            checkpoint_id=self.checkpoint_id,
            result=dict(self.result) if self.result else None,
            failure=self.failure,
            task_metadata=dict(self.metadata),
            provider_request_type=self.provider_request_type,
            task_category=self.task_category,
            execution_requirements=dict(self.execution_requirements) if self.execution_requirements else None,
            execution_plan=execution_plan_dict,
        )


class AutonomousTaskManager:
    """
    Manages autonomous task lifecycle.
    
    Handles task creation, execution coordination, dependencies, retries,
    and state transitions with event publishing.
    """

    def __init__(
        self,
        *,
        repository: AutonomousTaskRepository,
        dependency_repository: TaskDependencyRepository,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._repository = repository
        self._dependency_repository = dependency_repository
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

    def create(
        self,
        mission_id: str,
        name: str,
        description: str,
        *,
        parent_task_id: str | None = None,
        agent_id: str | None = None,
        capability_id: str | None = None,
        inputs: MappingProxyType[str, Any] | None = None,
        priority: int = 0,
        deadline: datetime | None = None,
        max_retries: int = 3,
        resource_budget: MappingProxyType[str, Any] | None = None,
        depends_on: tuple[str, ...] = (),
        metadata: MappingProxyType[str, Any] | None = None,
        provider_request_type: str | None = None,
        task_category: str | None = None,
        execution_requirements: MappingProxyType[str, Any] | None = None,
        execution_plan: Any | None = None,  # Optional ExecutionPlan
    ) -> AutonomousTask:
        """Create a new autonomous task."""
        now = datetime.now(UTC)
        
        # Determine initial status based on dependencies
        initial_status = AutonomousTaskStatus.CREATED
        if depends_on:
            initial_status = AutonomousTaskStatus.WAITING_FOR_DEPENDENCY

        task = AutonomousTask(
            id=self._generate_id(),
            mission_id=mission_id,
            parent_task_id=parent_task_id,
            agent_id=agent_id,
            name=name,
            description=description,
            capability_id=capability_id,
            inputs=inputs or MappingProxyType({}),
            status=initial_status,
            priority=priority,
            progress=0.0,
            created_at=now,
            started_at=None,
            updated_at=now,
            completed_at=None,
            deadline=deadline,
            max_retries=max_retries,
            retry_count=0,
            resource_budget=resource_budget or MappingProxyType({}),
            checkpoint_id=None,
            result=None,
            failure=None,
            metadata=metadata or MappingProxyType({}),
            provider_request_type=provider_request_type,
            task_category=task_category,
            execution_requirements=execution_requirements,
            execution_plan=execution_plan,
        )

        model = task.to_model()
        self._repository.create(model)

        # Create dependencies
        for dep_task_id in depends_on:
            self._create_dependency(task.id, dep_task_id)

        # For root tasks (no dependencies), immediately transition through SCHEDULED to READY
        # so the executor can claim them. Dependent tasks remain WAITING_FOR_DEPENDENCY
        # until _check_dependent_tasks promotes them.
        if not depends_on:
            # CREATED -> SCHEDULED
            task.status = AutonomousTaskStatus.SCHEDULED
            task.updated_at = datetime.now(UTC)
            model = task.to_model()
            self._repository.update(model)
            
            # SCHEDULED -> READY (no preconditions for root tasks)
            task.status = AutonomousTaskStatus.READY
            task.updated_at = datetime.now(UTC)
            model = task.to_model()
            self._repository.update(model)

        self._event_bus.publish("task.created", TaskCreatedEvent(
            event_id=self._generate_id(),
            event_type="task.created",
            mission_id=mission_id,
            task_id=task.id,
            name=name,
            description=description,
            capability_id=capability_id,
            inputs=inputs or MappingProxyType({}),
            priority=priority,
            max_retries=max_retries,
            resource_budget=resource_budget or MappingProxyType({}),
            deadline=deadline,
            provider_request_type=provider_request_type,
            task_category=task_category,
            execution_requirements=execution_requirements,
        ))

        self._logger.info("Created autonomous task '%s' for mission '%s' (status: %s)", task.id, mission_id, task.status.value)
        return task

    def _create_dependency(self, task_id: str, depends_on_task_id: str) -> None:
        """Create a task dependency."""
        from parika.core.autonomous.models import TaskDependencyModel
        from parika.core.autonomous.contracts import DependencyStatus
        
        dep = TaskDependencyModel(
            id=self._generate_id(),
            task_id=task_id,
            depends_on_task_id=depends_on_task_id,
            status=DependencyStatus.WAITING.value,
            created_at=datetime.now(UTC),
        )
        self._dependency_repository.create(dep)

    def get(self, task_id: str) -> AutonomousTask | None:
        """Get a task by ID."""
        model = self._repository.get(task_id)
        return AutonomousTask.from_model(model) if model else None

    def update(self, task: AutonomousTask) -> AutonomousTask:
        """Update a task."""
        task.updated_at = datetime.now(UTC)
        model = task.to_model()
        self._repository.update(model)
        return task

    def delete(self, task_id: str) -> bool:
        """Delete a task."""
        return self._repository.delete(task_id)

    def schedule(self, task_id: str) -> AutonomousTask | None:
        """Schedule a task for execution (CREATED -> SCHEDULED)."""
        task = self.get(task_id)
        if task is None:
            return None

        if not validate_task_transition(task.status, AutonomousTaskStatus.SCHEDULED):
            return None

        task.status = AutonomousTaskStatus.SCHEDULED
        task.updated_at = datetime.now(UTC)

        return self.update(task)

    def start(self, task_id: str, agent_id: str | None = None) -> AutonomousTask | None:
        """Start task execution (SCHEDULED/READY -> RUNNING)."""
        task = self.get(task_id)
        if task is None:
            return None

        if not validate_task_transition(task.status, AutonomousTaskStatus.RUNNING):
            self._logger.warning(
                "Invalid task transition from %s to RUNNING for task %s",
                task.status, task_id
            )
            return None

        task.status = AutonomousTaskStatus.RUNNING
        task.started_at = datetime.now(UTC)
        task.updated_at = datetime.now(UTC)
        if agent_id:
            task.agent_id = agent_id

        self.update(task)

        self._event_bus.publish("task.started", TaskStartedEvent(
            event_id=self._generate_id(),
            mission_id=task.mission_id,
            task_id=task.id,
            agent_id=agent_id,
            attempt_number=task.retry_count + 1,
        ))

        self._logger.info("Started task '%s'", task_id)
        return task

    def update_progress(self, task_id: str, progress: float, message: str | None = None) -> AutonomousTask | None:
        """Update task progress."""
        task = self.get(task_id)
        if task is None:
            return None

        task.progress = max(0.0, min(1.0, progress))
        task.updated_at = datetime.now(UTC)

        self.update(task)

        self._event_bus.publish("task.progress", TaskProgressEvent(
            event_id=self._generate_id(),
            mission_id=task.mission_id,
            task_id=task.id,
            progress=task.progress,
            message=message,
        ))

        return task

    def complete(self, task_id: str, result: MappingProxyType[str, Any] | None = None) -> AutonomousTask | None:
        """Complete a task successfully."""
        task = self.get(task_id)
        if task is None:
            return None

        if not validate_task_transition(task.status, AutonomousTaskStatus.COMPLETED):
            return None

        task.status = AutonomousTaskStatus.COMPLETED
        task.completed_at = datetime.now(UTC)
        task.progress = 1.0
        task.result = result
        task.updated_at = datetime.now(UTC)

        self.update(task)

        # Check and update dependent tasks
        self._check_dependent_tasks(task.id)

        self._event_bus.publish("task.completed", TaskCompletedEvent(
            event_id=self._generate_id(),
            mission_id=task.mission_id,
            task_id=task.id,
            result=result,
            attempt_number=task.retry_count + 1,
        ))

        # Phase 2: Also publish task.completed for WaitManager
        self._event_bus.publish("task.completed", {
            "event_id": self._generate_id(),
            "mission_id": task.mission_id,
            "task_id": task.id,
            "result": dict(result) if result else {},
            "completed_dependencies": [task.id],
        })

        self._logger.info("Completed task '%s'", task_id)
        return task

    def fail(
        self,
        task_id: str,
        failure: str,
        attempt_number: int | None = None,
    ) -> AutonomousTask | None:
        """Mark a task as failed."""
        task = self.get(task_id)
        if task is None:
            return None

        if not validate_task_transition(task.status, AutonomousTaskStatus.FAILED):
            return None

        task.status = AutonomousTaskStatus.FAILED
        task.failure = failure
        task.completed_at = datetime.now(UTC)
        task.updated_at = datetime.now(UTC)

        # Determine if retry is eligible
        retry_eligible = task.retry_count < task.max_retries
        if retry_eligible:
            task.retry_count += 1

        self.update(task)

        self._event_bus.publish("task.failed", TaskFailedEvent(
            event_id=self._generate_id(),
            mission_id=task.mission_id,
            task_id=task.id,
            failure=failure,
            attempt_number=attempt_number or (task.retry_count),
            retry_eligible=retry_eligible,
            retry_count=task.retry_count,
            max_retries=task.max_retries,
        ))

        # Phase 2: Also publish task.failed for WaitManager
        self._event_bus.publish("task.failed", {
            "event_id": self._generate_id(),
            "mission_id": task.mission_id,
            "task_id": task.id,
            "failure": failure,
            "attempt_number": attempt_number or (task.retry_count),
            "retry_eligible": retry_eligible,
            "retry_count": task.retry_count,
            "max_retries": task.max_retries,
        })

        self._logger.error("Task '%s' failed: %s (retry eligible: %s)", task_id, failure, retry_eligible)
        return task

    def retry(self, task_id: str) -> AutonomousTask | None:
        """Retry a failed task."""
        task = self.get(task_id)
        if task is None:
            return None

        if task.status != AutonomousTaskStatus.FAILED:
            return None

        if task.retry_count >= task.max_retries:
            return None

        if not validate_task_transition(task.status, AutonomousTaskStatus.RETRYING):
            return None

        task.status = AutonomousTaskStatus.RETRYING
        task.failure = None
        task.completed_at = None
        task.updated_at = datetime.now(UTC)

        self.update(task)

        # Transition to READY for next execution attempt
        task.status = AutonomousTaskStatus.READY
        task.updated_at = datetime.now(UTC)
        self.update(task)

        self._logger.info("Retrying task '%s' (attempt %d)", task_id, task.retry_count + 1)
        return task

    def cancel(self, task_id: str, reason: str | None = None) -> AutonomousTask | None:
        """Cancel a task."""
        task = self.get(task_id)
        if task is None:
            return None

        if not validate_task_transition(task.status, AutonomousTaskStatus.CANCELLED):
            return None

        task.status = AutonomousTaskStatus.CANCELLED
        task.completed_at = datetime.now(UTC)
        task.updated_at = datetime.now(UTC)

        self.update(task)

        self._event_bus.publish("task.cancelled", TaskCancelledEvent(
            event_id=self._generate_id(),
            mission_id=task.mission_id,
            task_id=task.id,
            reason=reason,
        ))

        self._logger.info("Cancelled task '%s': %s", task_id, reason)
        return task

    def pause(self, task_id: str, reason: str | None = None) -> AutonomousTask | None:
        """Pause a running task."""
        task = self.get(task_id)
        if task is None:
            return None

        if not validate_task_transition(task.status, AutonomousTaskStatus.PAUSED):
            return None

        task.status = AutonomousTaskStatus.PAUSED
        task.updated_at = datetime.now(UTC)

        self.update(task)

        self._event_bus.publish("task.paused", TaskPausedEvent(
            event_id=self._generate_id(),
            mission_id=task.mission_id,
            task_id=task.id,
            reason=reason,
        ))

        return task

    def resume(self, task_id: str) -> AutonomousTask | None:
        """Resume a paused task."""
        task = self.get(task_id)
        if task is None:
            return None

        if not validate_task_transition(task.status, AutonomousTaskStatus.RUNNING):
            return None

        task.status = AutonomousTaskStatus.RUNNING
        task.updated_at = datetime.now(UTC)

        self.update(task)

        self._event_bus.publish("task.resumed", TaskResumedEvent(
            event_id=self._generate_id(),
            mission_id=task.mission_id,
            task_id=task.id,
            attempt_number=task.retry_count + 1,
        ))

        # Phase 2: Also publish for WaitManager
        self._event_bus.publish("task.resumed", {
            "event_id": self._generate_id(),
            "mission_id": task.mission_id,
            "task_id": task.id,
        })

        return task

    def _check_dependent_tasks(self, completed_task_id: str) -> None:
        """Check if dependent tasks can now run."""
        dependents = self._dependency_repository.get_dependents_for_task(completed_task_id)
        
        for dep in dependents:
            if self._dependency_repository.are_all_dependencies_satisfied(dep.task_id):
                # Mark this dependency as satisfied
                self._dependency_repository.mark_satisfied(dep.task_id, completed_task_id)
                
                # Get the dependent task
                task = self.get(dep.task_id)
                if task and task.status == AutonomousTaskStatus.WAITING_FOR_DEPENDENCY:
                    # Transition to READY
                    task.status = AutonomousTaskStatus.READY
                    task.updated_at = datetime.now(UTC)
                    self.update(task)

                    self._event_bus.publish("task.waiting_for_dependency", TaskWaitingForDependencyEvent(
                        event_id=self._generate_id(),
                        mission_id=task.mission_id,
                        task_id=task.id,
                        dependency_task_id=completed_task_id,
                        dependency_status="satisfied",
                    ))

    def list_by_mission(self, mission_id: str) -> list[AutonomousTask]:
        """List all tasks for a mission."""
        models = self._repository.list_by_mission(mission_id)
        return [AutonomousTask.from_model(m) for m in models]

    def list_ready_to_run(self) -> list[AutonomousTask]:
        """List tasks ready to execute."""
        models = self._repository.list_ready_to_run()
        return [AutonomousTask.from_model(m) for m in models]

    def list_retrying(self) -> list[AutonomousTask]:
        """List tasks that are retrying."""
        models = self._repository.list_retrying()
        return [AutonomousTask.from_model(m) for m in models]

    def list_by_status(self, status: AutonomousTaskStatus) -> list[AutonomousTask]:
        """List tasks by status."""
        models = self._repository.list_by_status(status.value)
        return [AutonomousTask.from_model(m) for m in models]

    def _generate_id(self) -> str:
        from uuid import uuid4
        return uuid4().hex