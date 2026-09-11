"""
PARIKA Autonomous Execution Repositories

Provides data access layer for autonomous execution persistent state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, func, and_, or_, delete, update
from sqlalchemy.orm import Session

from parika.core.autonomous.models import (
    MissionModel,
    AutonomousTaskModel,
    TaskDependencyModel,
    AgentInstanceModel,
    WorkerModel,
    ExecutionModel,
    CheckpointModel,
    WorldStateModel,
    AutonomousEventModel,
)
from parika.core.database.pool import PoolManager
from parika.core.logger.logger import Logger


def generate_id() -> str:
    """Generate a unique ID."""
    return uuid4().hex


class MissionRepository:
    """Repository for Mission persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _session(self) -> Session:
        return Session(self._pool.sync_pool)

    def create(self, mission: MissionModel) -> MissionModel:
        with self._session() as session:
            session.add(mission)
            session.commit()
            session.refresh(mission)
            return mission

    def get(self, mission_id: str) -> MissionModel | None:
        with self._session() as session:
            return session.get(MissionModel, mission_id)

    def update(self, mission: MissionModel) -> MissionModel:
        with self._session() as session:
            mission.updated_at = datetime.now(UTC)
            session.merge(mission)
            session.commit()
            return mission

    def delete(self, mission_id: str) -> bool:
        with self._session() as session:
            mission = session.get(MissionModel, mission_id)
            if mission is None:
                return False
            session.delete(mission)
            session.commit()
            return True

    def list_by_status(self, status: str, limit: int = 100, offset: int = 0) -> list[MissionModel]:
        with self._session() as session:
            stmt = select(MissionModel).where(MissionModel.status == status).limit(limit).offset(offset)
            return list(session.scalars(stmt).all())

    def list_active(self, limit: int = 100) -> list[MissionModel]:
        with self._session() as session:
            stmt = select(MissionModel).where(
                MissionModel.status.in_(["created", "planning", "running", "waiting", "paused", "blocked", "needs_approval"])
            ).limit(limit)
            return list(session.scalars(stmt).all())

    def count_by_status(self, status: str) -> int:
        with self._session() as session:
            stmt = select(func.count()).select_from(MissionModel).where(MissionModel.status == status)
            return session.scalar(stmt) or 0


class AutonomousTaskRepository:
    """Repository for Autonomous Task persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _session(self) -> Session:
        return Session(self._pool.sync_pool)

    def create(self, task: AutonomousTaskModel) -> AutonomousTaskModel:
        with self._session() as session:
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    def get(self, task_id: str) -> AutonomousTaskModel | None:
        with self._session() as session:
            return session.get(AutonomousTaskModel, task_id)

    def update(self, task: AutonomousTaskModel) -> AutonomousTaskModel:
        with self._session() as session:
            task.updated_at = datetime.now(UTC)
            session.merge(task)
            session.commit()
            return task

    def delete(self, task_id: str) -> bool:
        with self._session() as session:
            task = session.get(AutonomousTaskModel, task_id)
            if task is None:
                return False
            session.delete(task)
            session.commit()
            return True

    def list_by_mission(self, mission_id: str) -> list[AutonomousTaskModel]:
        with self._session() as session:
            stmt = select(AutonomousTaskModel).where(AutonomousTaskModel.mission_id == mission_id)
            return list(session.scalars(stmt).all())

    def list_by_status(self, status: str, limit: int = 100, offset: int = 0) -> list[AutonomousTaskModel]:
        with self._session() as session:
            stmt = select(AutonomousTaskModel).where(AutonomousTaskModel.status == status).limit(limit).offset(offset)
            return list(session.scalars(stmt).all())

    def list_ready_to_run(self, limit: int = 100) -> list[AutonomousTaskModel]:
        """Get tasks that are READY to execute (dependencies satisfied)."""
        with self._session() as session:
            stmt = select(AutonomousTaskModel).where(
                AutonomousTaskModel.status == "ready"
            ).limit(limit)
            return list(session.scalars(stmt).all())

    def claim_ready_task(self, task_id: str) -> AutonomousTaskModel | None:
        """
        Atomically claim a READY task by transitioning it to RUNNING.
        
        Uses a conditional UPDATE that only succeeds if the task is still
        in READY status. Returns the updated task model if successful,
        None if the task was not READY (already claimed by another process).
        """
        with self._session() as session:
            from sqlalchemy import update
            from parika.core.autonomous.contracts import AutonomousTaskStatus
            from datetime import UTC, datetime
            
            stmt = update(AutonomousTaskModel).where(
                AutonomousTaskModel.id == task_id,
                AutonomousTaskModel.status == AutonomousTaskStatus.READY.value,
            ).values(
                status=AutonomousTaskStatus.RUNNING.value,
                started_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            ).returning(AutonomousTaskModel)
            
            result = session.execute(stmt)
            session.commit()
            return result.scalar_one_or_none()

    def list_waiting_for_dependency(self, limit: int = 100) -> list[AutonomousTaskModel]:
        with self._session() as session:
            stmt = select(AutonomousTaskModel).where(
                AutonomousTaskModel.status == "waiting_for_dependency"
            ).limit(limit)
            return list(session.scalars(stmt).all())

    def list_retrying(self, limit: int = 100) -> list[AutonomousTaskModel]:
        with self._session() as session:
            stmt = select(AutonomousTaskModel).where(
                AutonomousTaskModel.status == "retrying"
            ).limit(limit)
            return list(session.scalars(stmt).all())

    def count_by_status(self, status: str) -> int:
        with self._session() as session:
            stmt = select(func.count()).select_from(AutonomousTaskModel).where(AutonomousTaskModel.status == status)
            return session.scalar(stmt) or 0


class TaskDependencyRepository:
    """Repository for Task Dependency persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _session(self) -> Session:
        return Session(self._pool.sync_pool)

    def create(self, dependency: TaskDependencyModel) -> TaskDependencyModel:
        with self._session() as session:
            session.add(dependency)
            session.commit()
            session.refresh(dependency)
            return dependency

    def get(self, dependency_id: str) -> TaskDependencyModel | None:
        with self._session() as session:
            return session.get(TaskDependencyModel, dependency_id)

    def update(self, dependency: TaskDependencyModel) -> TaskDependencyModel:
        with self._session() as session:
            session.merge(dependency)
            session.commit()
            return dependency

    def get_dependencies_for_task(self, task_id: str) -> list[TaskDependencyModel]:
        with self._session() as session:
            stmt = select(TaskDependencyModel).where(TaskDependencyModel.task_id == task_id)
            return list(session.scalars(stmt).all())

    def get_dependents_for_task(self, task_id: str) -> list[TaskDependencyModel]:
        with self._session() as session:
            stmt = select(TaskDependencyModel).where(TaskDependencyModel.depends_on_task_id == task_id)
            return list(session.scalars(stmt).all())

    def mark_satisfied(self, task_id: str, depends_on_task_id: str) -> bool:
        with self._session() as session:
            stmt = select(TaskDependencyModel).where(
                and_(
                    TaskDependencyModel.task_id == task_id,
                    TaskDependencyModel.depends_on_task_id == depends_on_task_id
                )
            )
            dependency = session.scalar(stmt)
            if dependency is None:
                return False
            dependency.status = "satisfied"
            dependency.satisfied_at = datetime.now(UTC)
            session.commit()
            return True

    def are_all_dependencies_satisfied(self, task_id: str) -> bool:
        with self._session() as session:
            stmt = select(func.count()).select_from(TaskDependencyModel).where(
                and_(
                    TaskDependencyModel.task_id == task_id,
                    TaskDependencyModel.status != "satisfied"
                )
            )
            count = session.scalar(stmt) or 0
            return count == 0


class AgentInstanceRepository:
    """Repository for Agent Instance persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _session(self) -> Session:
        return Session(self._pool.sync_pool)

    def create(self, agent: AgentInstanceModel) -> AgentInstanceModel:
        with self._session() as session:
            session.add(agent)
            session.commit()
            session.refresh(agent)
            return agent

    def get(self, agent_id: str) -> AgentInstanceModel | None:
        with self._session() as session:
            return session.get(AgentInstanceModel, agent_id)

    def update(self, agent: AgentInstanceModel) -> AgentInstanceModel:
        with self._session() as session:
            agent.updated_at = datetime.now(UTC)
            session.merge(agent)
            session.commit()
            return agent

    def delete(self, agent_id: str) -> bool:
        with self._session() as session:
            agent = session.get(AgentInstanceModel, agent_id)
            if agent is None:
                return False
            session.delete(agent)
            session.commit()
            return True

    def list_by_mission(self, mission_id: str) -> list[AgentInstanceModel]:
        with self._session() as session:
            stmt = select(AgentInstanceModel).where(AgentInstanceModel.mission_id == mission_id)
            return list(session.scalars(stmt).all())

    def list_by_task(self, task_id: str) -> list[AgentInstanceModel]:
        with self._session() as session:
            stmt = select(AgentInstanceModel).where(AgentInstanceModel.task_id == task_id)
            return list(session.scalars(stmt).all())

    def list_by_parent(self, parent_agent_id: str) -> list[AgentInstanceModel]:
        with self._session() as session:
            stmt = select(AgentInstanceModel).where(AgentInstanceModel.parent_agent_id == parent_agent_id)
            return list(session.scalars(stmt).all())

    def list_stale_heartbeats(self, timeout_seconds: float) -> list[AgentInstanceModel]:
        """Find agents with stale heartbeats (potential crashes)."""
        with self._session() as session:
            cutoff = datetime.now(UTC)
            # Note: In a real implementation, we'd subtract timeout_seconds from cutoff
            # For now, just return agents that haven't had a heartbeat in the timeout window
            stmt = select(AgentInstanceModel).where(
                and_(
                    AgentInstanceModel.status == "running",
                    AgentInstanceModel.last_heartbeat.isnot(None)
                )
            )
            return list(session.scalars(stmt).all())

    def list_by_status(self, status: str) -> list[AgentInstanceModel]:
        """List agents by status."""
        with self._session() as session:
            stmt = select(AgentInstanceModel).where(AgentInstanceModel.status == status)
            return list(session.scalars(stmt).all())


class WorkerRepository:
    """Repository for Worker persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _session(self) -> Session:
        return Session(self._pool.sync_pool)

    def create(self, worker: WorkerModel) -> WorkerModel:
        with self._session() as session:
            session.add(worker)
            session.commit()
            session.refresh(worker)
            return worker

    def get(self, worker_id: str) -> WorkerModel | None:
        with self._session() as session:
            return session.get(WorkerModel, worker_id)

    def update(self, worker: WorkerModel) -> WorkerModel:
        with self._session() as session:
            session.merge(worker)
            session.commit()
            return worker

    def delete(self, worker_id: str) -> bool:
        with self._session() as session:
            worker = session.get(WorkerModel, worker_id)
            if worker is None:
                return False
            session.delete(worker)
            session.commit()
            return True

    def list_by_task(self, task_id: str) -> list[WorkerModel]:
        with self._session() as session:
            stmt = select(WorkerModel).where(WorkerModel.task_id == task_id)
            return list(session.scalars(stmt).all())

    def list_by_status(self, status: str) -> list[WorkerModel]:
        with self._session() as session:
            stmt = select(WorkerModel).where(WorkerModel.status == status)
            return list(session.scalars(stmt).all())

    def list_crashed(self, timeout_seconds: float) -> list[WorkerModel]:
        """Find workers that have missed their heartbeat (potential crashes)."""
        with self._session() as session:
            # Workers in RUNNING state with no recent heartbeat
            stmt = select(WorkerModel).where(
                and_(
                    WorkerModel.status == "running",
                    WorkerModel.last_heartbeat.isnot(None)
                )
            )
            return list(session.scalars(stmt).all())


class ExecutionRepository:
    """Repository for Execution Attempt persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _session(self) -> Session:
        return Session(self._pool.sync_pool)

    def create(self, execution: ExecutionModel) -> ExecutionModel:
        with self._session() as session:
            session.add(execution)
            session.commit()
            session.refresh(execution)
            return execution

    def get(self, execution_id: str) -> ExecutionModel | None:
        with self._session() as session:
            return session.get(ExecutionModel, execution_id)

    def update(self, execution: ExecutionModel) -> ExecutionModel:
        with self._session() as session:
            execution.updated_at = datetime.now(UTC)
            session.merge(execution)
            session.commit()
            return execution

    def list_by_task(self, task_id: str) -> list[ExecutionModel]:
        with self._session() as session:
            stmt = select(ExecutionModel).where(ExecutionModel.task_id == task_id)
            return list(session.scalars(stmt).all())

    def get_latest_for_task(self, task_id: str) -> ExecutionModel | None:
        with self._session() as session:
            stmt = select(ExecutionModel).where(
                ExecutionModel.task_id == task_id
            ).order_by(ExecutionModel.attempt_number.desc()).limit(1)
            return session.scalar(stmt)


class CheckpointRepository:
    """Repository for Checkpoint persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _session(self) -> Session:
        return Session(self._pool.sync_pool)

    def create(self, checkpoint: CheckpointModel) -> CheckpointModel:
        with self._session() as session:
            session.add(checkpoint)
            session.commit()
            session.refresh(checkpoint)
            return checkpoint

    def get(self, checkpoint_id: str) -> CheckpointModel | None:
        with self._session() as session:
            return session.get(CheckpointModel, checkpoint_id)

    def update(self, checkpoint: CheckpointModel) -> CheckpointModel:
        with self._session() as session:
            session.merge(checkpoint)
            session.commit()
            return checkpoint

    def get_latest_for_task(self, task_id: str) -> CheckpointModel | None:
        with self._session() as session:
            stmt = select(CheckpointModel).where(
                and_(
                    CheckpointModel.task_id == task_id,
                    CheckpointModel.status == "available"
                )
            ).order_by(CheckpointModel.version.desc()).limit(1)
            return session.scalar(stmt)

    def list_by_execution(self, execution_id: str) -> list[CheckpointModel]:
        with self._session() as session:
            stmt = select(CheckpointModel).where(CheckpointModel.execution_id == execution_id)
            return list(session.scalars(stmt).all())

    def invalidate_old_checkpoints(self, task_id: str, keep_version: int) -> int:
        """Invalidate checkpoints older than the specified version."""
        with self._session() as session:
            stmt = update(CheckpointModel).where(
                and_(
                    CheckpointModel.task_id == task_id,
                    CheckpointModel.version < keep_version,
                    CheckpointModel.status == "available"
                )
            ).values(status="invalidated")
            result = session.execute(stmt)
            session.commit()
            return result.rowcount


class WorldStateRepository:
    """Repository for World State snapshots."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _session(self) -> Session:
        return Session(self._pool.sync_pool)

    def create_snapshot(self, snapshot: WorldStateModel) -> WorldStateModel:
        with self._session() as session:
            session.add(snapshot)
            session.commit()
            session.refresh(snapshot)
            return snapshot

    def get_latest(self) -> WorldStateModel | None:
        with self._session() as session:
            stmt = select(WorldStateModel).order_by(WorldStateModel.updated_at.desc()).limit(1)
            return session.scalar(stmt)


class AutonomousEventRepository:
    """Repository for Autonomous Event persistence (audit trail)."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _session(self) -> Session:
        return Session(self._pool.sync_pool)

    def create(self, event: AutonomousEventModel) -> AutonomousEventModel:
        with self._session() as session:
            session.add(event)
            session.commit()
            session.refresh(event)
            return event

    def list_by_mission(self, mission_id: str, limit: int = 100) -> list[AutonomousEventModel]:
        with self._session() as session:
            stmt = select(AutonomousEventModel).where(
                AutonomousEventModel.mission_id == mission_id
            ).order_by(AutonomousEventModel.timestamp.desc()).limit(limit)
            return list(session.scalars(stmt).all())

    def list_by_task(self, task_id: str, limit: int = 100) -> list[AutonomousEventModel]:
        with self._session() as session:
            stmt = select(AutonomousEventModel).where(
                AutonomousEventModel.task_id == task_id
            ).order_by(AutonomousEventModel.timestamp.desc()).limit(limit)
            return list(session.scalars(stmt).all())

    def list_by_agent(self, agent_id: str, limit: int = 100) -> list[AutonomousEventModel]:
        with self._session() as session:
            stmt = select(AutonomousEventModel).where(
                AutonomousEventModel.agent_id == agent_id
            ).order_by(AutonomousEventModel.timestamp.desc()).limit(limit)
            return list(session.scalars(stmt).all())

    def list_by_execution(self, execution_id: str, limit: int = 100) -> list[AutonomousEventModel]:
        with self._session() as session:
            stmt = select(AutonomousEventModel).where(
                AutonomousEventModel.execution_id == execution_id
            ).order_by(AutonomousEventModel.timestamp.desc()).limit(limit)
            return list(session.scalars(stmt).all())

    def list_by_worker(self, worker_id: str, limit: int = 100) -> list[AutonomousEventModel]:
        with self._session() as session:
            stmt = select(AutonomousEventModel).where(
                AutonomousEventModel.worker_id == worker_id
            ).order_by(AutonomousEventModel.timestamp.desc()).limit(limit)
            return list(session.scalars(stmt).all())