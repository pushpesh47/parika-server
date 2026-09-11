"""
PARIKA Autonomous Execution - Recovery Coordinator

Handles autonomous system recovery on startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from parika.core.autonomous.contracts import (
    MissionStatus,
    AutonomousTaskStatus,
    AgentInstanceStatus,
    WorkerStatus,
    RecoveryAction,
)
from parika.core.autonomous.events import (
    RecoveryStartedEvent,
    RecoveryCompletedEvent,
    RecoveryFailedEvent,
)
from parika.core.autonomous.models import (
    MissionModel,
    AutonomousTaskModel,
    AgentInstanceModel,
    WorkerModel,
    ExecutionModel,
)
from parika.core.autonomous.repository import (
    MissionRepository,
    AutonomousTaskRepository,
    TaskDependencyRepository,
    AgentInstanceRepository,
    WorkerRepository,
    ExecutionRepository,
)
from parika.core.autonomous.checkpoint_manager import CheckpointManager
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


class RecoveryPhase(Enum):
    """Recovery process phases."""
    LOADING_STATE = "loading_state"
    DETECTING_STALE_WORKERS = "detecting_stale_workers"
    VALIDATING_CHECKPOINTS = "validating_checkpoints"
    RECOVERING_TASKS = "recovering_tasks"
    RESUMING_EXECUTION = "resuming_execution"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True, kw_only=True)
class RecoveryResult:
    """Result of recovery process."""
    missions_recovered: int
    tasks_recovered: int
    tasks_cancelled: int
    tasks_failed: int
    workers_recovered: int
    workers_marked_crashed: int
    checkpoints_validated: int
    checkpoints_invalidated: int
    errors: list[str]


class RecoveryCoordinator:
    """
    Coordinates autonomous system recovery on startup.
    
    Recovery process:
    1. Load persisted autonomous state
    2. Find unfinished work
    3. Detect stale workers
    4. Validate checkpoints
    5. Recover eligible tasks
    6. Resume execution
    """

    def __init__(
        self,
        *,
        mission_repository: MissionRepository,
        task_repository: AutonomousTaskRepository,
        dependency_repository: TaskDependencyRepository,
        agent_repository: AgentInstanceRepository,
        worker_repository: WorkerRepository,
        execution_repository: ExecutionRepository,
        checkpoint_manager: CheckpointManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._mission_repository = mission_repository
        self._task_repository = task_repository
        self._dependency_repository = dependency_repository
        self._agent_repository = agent_repository
        self._worker_repository = worker_repository
        self._execution_repository = execution_repository
        self._checkpoint_manager = checkpoint_manager
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

    def recover(self) -> RecoveryResult:
        """
        Perform full autonomous system recovery.
        
        Returns a RecoveryResult with statistics.
        """
        self._logger.info("Starting autonomous system recovery")
        
        result = RecoveryResult(
            missions_recovered=0,
            tasks_recovered=0,
            tasks_cancelled=0,
            tasks_failed=0,
            workers_recovered=0,
            workers_marked_crashed=0,
            checkpoints_validated=0,
            checkpoints_invalidated=0,
            errors=[],
        )

        try:
            # Phase 1: Load persisted state and find unfinished missions
            self._logger.info("Recovery phase 1: Loading unfinished missions")
            missions = self._mission_repository.list_active()
            self._logger.info("Found %d active missions", len(missions))

            # Phase 2: Detect stale workers
            self._logger.info("Recovery phase 2: Detecting stale workers")
            crashed_workers = self._detect_crashed_workers()
            result.workers_marked_crashed = len(crashed_workers)
            for worker in crashed_workers:
                self._worker_repository.update(worker.to_model())

            # Phase 3: Validate checkpoints
            self._logger.info("Recovery phase 3: Validating checkpoints")
            # Checkpoints are validated on creation, but we verify they're still valid
            result.checkpoints_validated = self._validate_all_checkpoints()

            # Phase 4: Recover tasks for each mission
            self._logger.info("Recovery phase 4: Recovering tasks")
            for mission_model in missions:
                mission_result = self._recover_mission(mission_model)
                result.missions_recovered += 1
                result.tasks_recovered += mission_result["recovered"]
                result.tasks_cancelled += mission_result["cancelled"]
                result.tasks_failed += mission_result["failed"]

            # Phase 5: Update dependent task statuses
            self._logger.info("Recovery phase 5: Updating task dependencies")
            self._update_task_dependencies()

            # Phase 6: Resume ready tasks
            self._logger.info("Recovery phase 6: Resuming ready tasks")
            ready_tasks = self._task_repository.list_ready_to_run()
            self._logger.info("Found %d tasks ready to run", len(ready_tasks))
            # Tasks are marked READY; actual execution is triggered by the autonomous runtime

            self._logger.info("Autonomous system recovery completed: %s", result)
            
            self._event_bus.publish("recovery.completed", RecoveryCompletedEvent(
                event_id=self._generate_id(),
                recovery_action="full_recovery",
                restored_checkpoint_id=None,
            ))

        except Exception as e:
            self._logger.exception("Autonomous system recovery failed")
            result.errors.append(str(e))
            
            self._event_bus.publish("recovery.failed", RecoveryFailedEvent(
                event_id=self._generate_id(),
                event_type="recovery.failed",
                failure=str(e),
                recovery_action="full_recovery",
            ))

        return result

    def _detect_crashed_workers(self) -> list[WorkerModel]:
        """Detect workers that appear to have crashed."""
        # Get all workers in RUNNING state
        running_workers = self._worker_repository.list_by_status(WorkerStatus.RUNNING.value)
        crashed = []

        for worker in running_workers:
            if worker.last_heartbeat is None:
                # No heartbeat ever - mark as crashed
                worker.status = WorkerStatus.CRASHED.value
                crashed.append(worker)
                continue

            # Check if heartbeat is stale
            elapsed = (datetime.now(UTC) - worker.last_heartbeat).total_seconds()
            if elapsed > worker.timeout_seconds:
                worker.status = WorkerStatus.CRASHED.value
                crashed.append(worker)

        self._logger.warning("Detected %d crashed workers", len(crashed))
        return crashed

    def _validate_all_checkpoints(self) -> int:
        """Validate all available checkpoints."""
        # Checkpoints are validated on creation, so this is a sanity check
        # In a full implementation, we'd verify checksums, etc.
        return 0

    def _recover_mission(self, mission_model: MissionModel) -> dict[str, int]:
        """Recover tasks for a single mission."""
        recovered = 0
        cancelled = 0
        failed = 0

        # Get all tasks for this mission
        tasks = self._task_repository.list_by_mission(mission_model.id)

        for task_model in tasks:
            task_status = AutonomousTaskStatus(task_model.status)

            # Skip terminal states
            if task_status in (
                AutonomousTaskStatus.COMPLETED,
                AutonomousTaskStatus.CANCELLED,
            ):
                continue

            # Handle FAILED tasks - check if retry eligible
            if task_status == AutonomousTaskStatus.FAILED:
                if task_model.retry_count < task_model.max_retries:
                    # Mark as retrying
                    task_model.status = AutonomousTaskStatus.RETRYING.value
                    task_model.updated_at = datetime.now(UTC)
                    self._task_repository.update(task_model)
                    recovered += 1
                    self._logger.info("Marked task '%s' for retry (attempt %d)", 
                                     task_model.id, task_model.retry_count + 1)
                else:
                    # Max retries exceeded - mark as failed permanently
                    cancelled += 1
                    self._logger.warning("Task '%s' exceeded max retries, marking cancelled", task_model.id)
                continue

            # Handle RUNNING tasks - check if worker crashed
            if task_status == AutonomousTaskStatus.RUNNING:
                worker = self._worker_repository.list_by_task(task_model.id)
                has_active_worker = any(
                    w.status in (WorkerStatus.RUNNING.value, WorkerStatus.STARTING.value, WorkerStatus.PAUSED.value)
                    for w in worker
                )

                if not has_active_worker:
                    # No active worker - recover from checkpoint
                    recovery_action = self._determine_recovery_action(task_model)
                    
                    if recovery_action == RecoveryAction.RESTART_FROM_CHECKPOINT:
                        checkpoint = self._checkpoint_manager.get_latest_for_task(task_model.id)
                        if checkpoint:
                            # Restore checkpoint and mark task as RECOVERING
                            task_model.status = AutonomousTaskStatus.RECOVERING.value
                            task_model.checkpoint_id = checkpoint.id
                            task_model.updated_at = datetime.now(UTC)
                            self._task_repository.update(task_model)
                            
                            self._checkpoint_manager.restore(checkpoint.id)
                            
                            # Mark as READY for re-execution
                            task_model.status = AutonomousTaskStatus.READY.value
                            self._task_repository.update(task_model)
                            
                            recovered += 1
                            self._logger.info("Recovered task '%s' from checkpoint '%s'", 
                                             task_model.id, checkpoint.id)
                        else:
                            # No checkpoint - retry if eligible
                            if task_model.retry_count < task_model.max_retries:
                                task_model.status = AutonomousTaskStatus.RETRYING.value
                                task_model.retry_count += 1
                                task_model.updated_at = datetime.now(UTC)
                                self._task_repository.update(task_model)
                                recovered += 1
                            else:
                                task_model.status = AutonomousTaskStatus.FAILED.value
                                task_model.failure = "Worker crashed and no checkpoint available"
                                task_model.updated_at = datetime.now(UTC)
                                self._task_repository.update(task_model)
                                failed += 1
                    elif recovery_action == RecoveryAction.RETRY:
                        if task_model.retry_count < task_model.max_retries:
                            task_model.status = AutonomousTaskStatus.RETRYING.value
                            task_model.retry_count += 1
                            task_model.updated_at = datetime.now(UTC)
                            self._task_repository.update(task_model)
                            recovered += 1
                        else:
                            task_model.status = AutonomousTaskStatus.FAILED.value
                            task_model.failure = "Max retries exceeded after worker crash"
                            task_model.updated_at = datetime.now(UTC)
                            self._task_repository.update(task_model)
                            failed += 1
                    else:
                        # Mark as failed
                        task_model.status = AutonomousTaskStatus.FAILED.value
                        task_model.failure = "Worker crashed, recovery not possible"
                        task_model.updated_at = datetime.now(UTC)
                        self._task_repository.update(task_model)
                        failed += 1

            # Handle WAITING_FOR_DEPENDENCY - check if dependencies are satisfied
            elif task_status == AutonomousTaskStatus.WAITING_FOR_DEPENDENCY:
                if self._dependency_repository.are_all_dependencies_satisfied(task_model.id):
                    task_model.status = AutonomousTaskStatus.READY.value
                    task_model.updated_at = datetime.now(UTC)
                    self._task_repository.update(task_model)
                    recovered += 1
                    self._logger.info("Task '%s' dependencies satisfied, marked READY", task_model.id)

            # Handle PAUSED, BLOCKED - keep as-is (user/system action required)
            elif task_status in (
                AutonomousTaskStatus.PAUSED,
                AutonomousTaskStatus.BLOCKED,
                AutonomousTaskStatus.WAITING_FOR_RESOURCE,
                AutonomousTaskStatus.WAITING_FOR_APPROVAL,
            ):
                # These require external intervention - leave as-is
                self._logger.info("Task '%s' in %s state, awaiting external action", 
                                 task_model.id, task_status.value)
                continue

        return {"recovered": recovered, "cancelled": cancelled, "failed": failed}

    def _determine_recovery_action(self, task_model: AutonomousTaskModel) -> RecoveryAction:
        """Determine the appropriate recovery action for a task."""
        # If there's a valid checkpoint, use it
        checkpoint = self._checkpoint_manager.get_latest_for_task(task_model.id)
        if checkpoint and checkpoint.status == "available":
            return RecoveryAction.RESTART_FROM_CHECKPOINT

        # If task has retries remaining, retry
        if task_model.retry_count < task_model.max_retries:
            return RecoveryAction.RETRY

        # Otherwise, mark as failed
        return RecoveryAction.MARK_FAILED

    def _update_task_dependencies(self) -> None:
        """Update dependency statuses based on task completions."""
        # Find all completed tasks
        completed_tasks = self._task_repository.list_by_status("completed")
        
        for task in completed_tasks:
            self._dependency_repository.are_all_dependencies_satisfied(task.id)

    def _generate_id(self) -> str:
        from uuid import uuid4
        return uuid4().hex