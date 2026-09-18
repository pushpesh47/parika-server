"""
PARIKA Autonomous Execution - Worker Manager

Manages the lifecycle of workers that execute autonomous tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Callable

from parika.core.autonomous.contracts import WorkerStatus, validate_worker_transition
from parika.core.autonomous.events import (
    WorkerSpawnedEvent,
    WorkerStartedEvent,
    WorkerHeartbeatEvent,
    WorkerFailedEvent,
    WorkerCancelledEvent,
)
from parika.core.autonomous.models import WorkerModel, ExecutionModel
from parika.core.autonomous.repository import WorkerRepository, ExecutionRepository
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(slots=True, kw_only=True)
class Worker:
    """Worker domain model."""
    id: str
    task_id: str
    execution_id: str
    status: WorkerStatus
    started_at: datetime
    last_activity: datetime
    last_heartbeat: datetime | None
    heartbeat_interval_seconds: float
    timeout_seconds: float
    result: MappingProxyType[str, Any] | None
    error: str | None
    metadata: MappingProxyType[str, Any]

    @classmethod
    def from_model(cls, model: WorkerModel) -> "Worker":
        return cls(
            id=model.id,
            task_id=model.task_id,
            execution_id=model.execution_id,
            status=WorkerStatus(model.status),
            started_at=model.started_at,
            last_activity=model.last_activity,
            last_heartbeat=model.last_heartbeat,
            heartbeat_interval_seconds=model.heartbeat_interval_seconds,
            timeout_seconds=model.timeout_seconds,
            result=MappingProxyType(model.result) if model.result else None,
            error=model.error,
            metadata=MappingProxyType(model.worker_metadata),
        )

    def to_model(self) -> WorkerModel:
        return WorkerModel(
            id=self.id,
            task_id=self.task_id,
            execution_id=self.execution_id,
            status=self.status.value,
            started_at=self.started_at,
            last_activity=self.last_activity,
            last_heartbeat=self.last_heartbeat,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            timeout_seconds=self.timeout_seconds,
            result=dict(self.result) if self.result else None,
            error=self.error,
            metadata=dict(self.metadata),
        )


@dataclass(slots=True, kw_only=True)
class Execution:
    """Execution attempt domain model."""
    id: str
    task_id: str
    worker_id: str | None
    status: str
    attempt_number: int
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    checkpoint_id: str | None
    result: MappingProxyType[str, Any] | None
    error: str | None
    metadata: MappingProxyType[str, Any]
    step_index: int = 0

    @classmethod
    def from_model(cls, model: ExecutionModel) -> "Execution":
        return cls(
            id=model.id,
            task_id=model.task_id,
            worker_id=model.worker_id,
            status=model.status,
            attempt_number=model.attempt_number,
            started_at=model.started_at,
            updated_at=model.updated_at,
            completed_at=model.completed_at,
            checkpoint_id=model.checkpoint_id,
            result=MappingProxyType(model.result) if model.result else None,
            error=model.error,
            metadata=MappingProxyType(model.execution_metadata),
            step_index=model.step_index,
        )

    def to_model(self) -> ExecutionModel:
        return ExecutionModel(
            id=self.id,
            task_id=self.task_id,
            worker_id=self.worker_id,
            status=self.status,
            attempt_number=self.attempt_number,
            started_at=self.started_at,
            updated_at=self.updated_at,
            completed_at=self.completed_at,
            checkpoint_id=self.checkpoint_id,
            result=dict(self.result) if self.result else None,
            error=self.error,
            metadata=dict(self.metadata),
            step_index=self.step_index,
        )


class WorkerManager:
    """
    Manages worker lifecycle for autonomous task execution.
    
    Workers execute tasks independently of HTTP request lifecycle.
    Supports heartbeat monitoring, crash detection, and recovery.
    """

    def __init__(
        self,
        *,
        worker_repository: WorkerRepository,
        execution_repository: ExecutionRepository,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._worker_repository = worker_repository
        self._execution_repository = execution_repository
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

    def spawn(
        self,
        task_id: str,
        *,
        heartbeat_interval_seconds: float = 30.0,
        timeout_seconds: float = 120.0,
        metadata: MappingProxyType[str, Any] | None = None,
    ) -> tuple[Worker, Execution]:
        """Spawn a new worker and execution attempt for a task."""
        now = datetime.now(UTC)
        
        # Create execution attempt
        executions = self._execution_repository.list_by_task(task_id)
        attempt_number = len(executions) + 1
        
        execution = Execution(
            id=self._generate_id(),
            task_id=task_id,
            worker_id=None,  # Will be set after worker creation (nullable FK)
            status="created",
            attempt_number=attempt_number,
            started_at=now,
            updated_at=now,
            completed_at=None,
            checkpoint_id=None,
            result=None,
            error=None,
            metadata=MappingProxyType({}),
        )

        # Create worker
        worker = Worker(
            id=self._generate_id(),
            task_id=task_id,
            execution_id=execution.id,
            status=WorkerStatus.SPAWNED,
            started_at=now,
            last_activity=now,
            last_heartbeat=None,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            timeout_seconds=timeout_seconds,
            result=None,
            error=None,
            metadata=metadata or MappingProxyType({}),
        )

        # Persist execution FIRST with NULL worker_id (Worker FK references it)
        self._execution_repository.create(execution.to_model())

        # Persist worker SECOND (Execution now exists)
        self._worker_repository.create(worker.to_model())

        # Now update execution with worker ID and persist the update
        execution.worker_id = worker.id
        self._execution_repository.update(execution.to_model())

        self._event_bus.publish("worker.spawned", WorkerSpawnedEvent(
            event_id=self._generate_id(),
            event_type="worker.spawned",
            task_id=task_id,
            worker_id=worker.id,
            execution_id=execution.id,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            timeout_seconds=timeout_seconds,
        ))

        self._logger.info("Spawned worker '%s' for task '%s' (attempt %d)", 
                         worker.id, task_id, attempt_number)
        return worker, execution

    def start(self, worker_id: str) -> Worker | None:
        """Start a worker (SPAWNED -> STARTING -> RUNNING)."""
        worker = self._worker_repository.get(worker_id)
        if worker is None:
            return None

        if not validate_worker_transition(WorkerStatus(worker.status), WorkerStatus.STARTING):
            return None

        worker.status = WorkerStatus.STARTING.value
        self._worker_repository.update(worker)

        if not validate_worker_transition(WorkerStatus.STARTING, WorkerStatus.RUNNING):
            return None

        worker.status = WorkerStatus.RUNNING.value
        worker.last_activity = datetime.now(UTC)
        self._worker_repository.update(worker)

        # Update execution status
        execution = self._execution_repository.get(worker.execution_id)
        if execution:
            execution.status = "running"
            execution.updated_at = datetime.now(UTC)
            self._execution_repository.update(execution)

        self._event_bus.publish("worker.started", WorkerStartedEvent(
            event_id=self._generate_id(),
            event_type="worker.started",
            task_id=worker.task_id,
            worker_id=worker.id,
            execution_id=worker.execution_id,
        ))

        self._logger.info("Started worker '%s'", worker_id)
        return Worker.from_model(worker)

    def heartbeat(
        self,
        worker_id: str,
        *,
        progress: float | None = None,
        message: str | None = None,
    ) -> Worker | None:
        """Record a worker heartbeat."""
        worker = self._worker_repository.get(worker_id)
        if worker is None:
            return None

        if worker.status != WorkerStatus.RUNNING.value:
            return None

        worker.last_heartbeat = datetime.now(UTC)
        worker.last_activity = datetime.now(UTC)
        self._worker_repository.update(worker)

        self._event_bus.publish("worker.heartbeat", WorkerHeartbeatEvent(
            event_id=self._generate_id(),
            event_type="worker.heartbeat",
            task_id=worker.task_id,
            worker_id=worker.id,
            status=worker.status,
            progress=progress,
            message=message,
        ))

        return Worker.from_model(worker)

    def complete(self, worker_id: str, result: MappingProxyType[str, Any] | None = None) -> Worker | None:
        """Mark worker as completed."""
        worker = self._worker_repository.get(worker_id)
        if worker is None:
            return None

        if not validate_worker_transition(WorkerStatus(worker.status), WorkerStatus.COMPLETING):
            return None

        worker.status = WorkerStatus.COMPLETING.value
        self._worker_repository.update(worker)

        if not validate_worker_transition(WorkerStatus.COMPLETING, WorkerStatus.COMPLETED):
            return None

        worker.status = WorkerStatus.COMPLETED.value
        # Convert MappingProxyType to dict for JSON serialization
        worker.result = dict(result) if result else None
        worker.last_activity = datetime.now(UTC)
        self._worker_repository.update(worker)

        # Update execution
        execution = self._execution_repository.get(worker.execution_id)
        if execution:
            execution.status = "completed"
            execution.completed_at = datetime.now(UTC)
            # Convert MappingProxyType to dict for JSON serialization
            execution.result = dict(result) if result else None
            execution.updated_at = datetime.now(UTC)
            self._execution_repository.update(execution)

        self._logger.info("Worker '%s' completed", worker_id)
        return Worker.from_model(worker)

    def fail(self, worker_id: str, error: str, crash_detected: bool = False) -> Worker | None:
        """Mark worker as failed."""
        worker = self._worker_repository.get(worker_id)
        if worker is None:
            return None

        if not validate_worker_transition(WorkerStatus(worker.status), WorkerStatus.FAILING):
            return None

        worker.status = WorkerStatus.FAILING.value
        self._worker_repository.update(worker)

        if not validate_worker_transition(WorkerStatus.FAILING, WorkerStatus.FAILED):
            return None

        worker.status = WorkerStatus.FAILED.value
        worker.error = error
        worker.last_activity = datetime.now(UTC)
        self._worker_repository.update(worker)

        # Update execution
        execution = self._execution_repository.get(worker.execution_id)
        if execution:
            execution.status = "failed"
            execution.completed_at = datetime.now(UTC)
            execution.error = error
            execution.updated_at = datetime.now(UTC)
            self._execution_repository.update(execution)

        self._event_bus.publish("worker.failed", WorkerFailedEvent(
            event_id=self._generate_id(),
            event_type="worker.failed",
            task_id=worker.task_id,
            worker_id=worker.id,
            failure=error,
            crash_detected=crash_detected,
        ))

        self._logger.error("Worker '%s' failed: %s (crash: %s)", worker_id, error, crash_detected)
        return Worker.from_model(worker)

    def cancel(self, worker_id: str, reason: str | None = None) -> Worker | None:
        """Cancel a worker."""
        worker = self._worker_repository.get(worker_id)
        if worker is None:
            return None

        if not validate_worker_transition(WorkerStatus(worker.status), WorkerStatus.CANCELLING):
            return None

        worker.status = WorkerStatus.CANCELLING.value
        self._worker_repository.update(worker)

        if not validate_worker_transition(WorkerStatus.CANCELLING, WorkerStatus.CANCELLED):
            return None

        worker.status = WorkerStatus.CANCELLED.value
        worker.error = reason
        worker.last_activity = datetime.now(UTC)
        self._worker_repository.update(worker)

        # Update execution
        execution = self._execution_repository.get(worker.execution_id)
        if execution:
            execution.status = "cancelled"
            execution.completed_at = datetime.now(UTC)
            execution.error = reason
            execution.updated_at = datetime.now(UTC)
            self._execution_repository.update(execution)

        self._event_bus.publish("worker.cancelled", WorkerCancelledEvent(
            event_id=self._generate_id(),
            event_type="worker.cancelled",
            task_id=worker.task_id,
            worker_id=worker.id,
            reason=reason,
        ))

        self._logger.info("Worker '%s' cancelled: %s", worker_id, reason)
        return Worker.from_model(worker)

    def pause(self, worker_id: str) -> Worker | None:
        """Pause a running worker."""
        worker = self._worker_repository.get(worker_id)
        if worker is None:
            return None

        if not validate_worker_transition(WorkerStatus(worker.status), WorkerStatus.PAUSING):
            return None

        worker.status = WorkerStatus.PAUSING.value
        self._worker_repository.update(worker)

        if not validate_worker_transition(WorkerStatus.PAUSING, WorkerStatus.PAUSED):
            return None

        worker.status = WorkerStatus.PAUSED.value
        self._worker_repository.update(worker)

        return Worker.from_model(worker)

    def resume(self, worker_id: str) -> Worker | None:
        """Resume a paused worker."""
        worker = self._worker_repository.get(worker_id)
        if worker is None:
            return None

        if not validate_worker_transition(WorkerStatus(worker.status), WorkerStatus.RESUMING):
            return None

        worker.status = WorkerStatus.RESUMING.value
        self._worker_repository.update(worker)

        if not validate_worker_transition(WorkerStatus.RESUMING, WorkerStatus.RUNNING):
            return None

        worker.status = WorkerStatus.RUNNING.value
        worker.last_activity = datetime.now(UTC)
        self._worker_repository.update(worker)

        return Worker.from_model(worker)

    def detect_crashed_workers(self, timeout_seconds: float | None = None) -> list[Worker]:
        """Detect workers that have missed their heartbeat."""
        # This is a simplified implementation
        # In production, we'd check last_heartbeat against timeout
        workers = self._worker_repository.list_by_status(WorkerStatus.RUNNING.value)
        crashed = []
        
        for worker in workers:
            if worker.last_heartbeat is None:
                continue
                
            # Use worker's own timeout or provided timeout
            timeout = timeout_seconds or worker.timeout_seconds
            elapsed = (datetime.now(UTC) - worker.last_heartbeat).total_seconds()
            
            if elapsed > timeout:
                crashed.append(Worker.from_model(worker))
                
        return crashed

    def mark_crashed(self, worker_id: str) -> Worker | None:
        """Mark a worker as crashed (detected via heartbeat timeout)."""
        worker = self._worker_repository.get(worker_id)
        if worker is None:
            return None

        if not validate_worker_transition(WorkerStatus(worker.status), WorkerStatus.CRASHED):
            return None

        worker.status = WorkerStatus.CRASHED.value
        self._worker_repository.update(worker)

        self._logger.warning("Worker '%s' marked as crashed (heartbeat timeout)", worker_id)
        return Worker.from_model(worker)

    def get_worker(self, worker_id: str) -> Worker | None:
        """Get a worker by ID."""
        model = self._worker_repository.get(worker_id)
        return Worker.from_model(model) if model else None

    def get_execution(self, execution_id: str) -> Execution | None:
        """Get an execution by ID."""
        model = self._execution_repository.get(execution_id)
        return Execution.from_model(model) if model else None

    def list_workers_by_task(self, task_id: str) -> list[Worker]:
        """List all workers for a task."""
        models = self._worker_repository.list_by_task(task_id)
        return [Worker.from_model(m) for m in models]

    def list_executions_by_task(self, task_id: str) -> list[Execution]:
        """List all executions for a task."""
        models = self._execution_repository.list_by_task(task_id)
        return [Execution.from_model(m) for m in models]

    def _generate_id(self) -> str:
        from uuid import uuid4
        return uuid4().hex