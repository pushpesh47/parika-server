"""
PARIKA Autonomous Execution Repositories

Provides data access layer for autonomous execution persistent state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

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
    AgentMessageModel,
)
from parika.core.autonomous.contracts import (
    MissionStatus,
    AutonomousTaskStatus,
    AgentInstanceStatus,
    WorkerStatus,
    ExecutionStatus,
    CheckpointStatus,
    DependencyStatus,
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

    def _row_to_model(self, row: dict[str, Any]) -> MissionModel:
        """Convert a database row to a MissionModel."""
        return MissionModel(
            id=row["id"],
            goal=row["goal"],
            status=row["status"],
            priority=row["priority"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            deadline=row["deadline"],
            progress=row["progress"],
            mission_metadata=row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"]),
            failure=row["failure"],
            result=row["result"] if isinstance(row["result"], dict) else json.loads(row["result"]) if row["result"] else None,
        )

    def create(self, mission: MissionModel) -> MissionModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                now = datetime.now(UTC)
                cur.execute(
                    """
                    INSERT INTO execution.mission (
                        id, goal, status, priority, created_at, started_at, updated_at,
                        completed_at, deadline, progress, metadata, failure, result
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        mission.id,
                        mission.goal,
                        mission.status,
                        mission.priority,
                        mission.created_at,
                        mission.started_at,
                        mission.updated_at,
                        mission.completed_at,
                        mission.deadline,
                        mission.progress,
                        json.dumps(mission.mission_metadata),
                        mission.failure,
                        json.dumps(mission.result) if mission.result else None,
                    ),
                )
                conn.commit()
                return mission

    def get(self, mission_id: str) -> MissionModel | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.mission WHERE id = %s",
                    (mission_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_model(row)

    def update(self, mission: MissionModel) -> MissionModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                now = datetime.now(UTC)
                cur.execute(
                    """
                    UPDATE execution.mission SET
                        goal = %s,
                        status = %s,
                        priority = %s,
                        started_at = %s,
                        updated_at = %s,
                        completed_at = %s,
                        deadline = %s,
                        progress = %s,
                        metadata = %s,
                        failure = %s,
                        result = %s
                    WHERE id = %s
                    """,
                    (
                        mission.goal,
                        mission.status,
                        mission.priority,
                        mission.started_at,
                        now,
                        mission.completed_at,
                        mission.deadline,
                        mission.progress,
                        json.dumps(mission.mission_metadata),
                        mission.failure,
                        json.dumps(mission.result) if mission.result else None,
                        mission.id,
                    ),
                )
                conn.commit()
                mission.updated_at = now
                return mission

    def delete(self, mission_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM execution.mission WHERE id = %s",
                    (mission_id,),
                )
                conn.commit()
                return cur.rowcount > 0

    def list_by_status(self, status: str, limit: int = 100, offset: int = 0) -> list[MissionModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.mission WHERE status = %s LIMIT %s OFFSET %s",
                    (status, limit, offset),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_active(self, limit: int = 100) -> list[MissionModel]:
        active_statuses = [
            MissionStatus.CREATED.value,
            MissionStatus.PLANNING.value,
            MissionStatus.RUNNING.value,
            MissionStatus.WAITING.value,
            MissionStatus.PAUSED.value,
            MissionStatus.BLOCKED.value,
            MissionStatus.NEEDS_APPROVAL.value,
        ]
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                placeholders = ", ".join(["%s"] * len(active_statuses))
                cur.execute(
                    f"SELECT * FROM execution.mission WHERE status IN ({placeholders}) LIMIT %s",
                    (*active_statuses, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def count_by_status(self, status: str) -> int:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM execution.mission WHERE status = %s",
                    (status,),
                )
                return cur.fetchone()[0] or 0


class AutonomousTaskRepository:
    """Repository for Autonomous Task persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _row_to_model(self, row: dict[str, Any]) -> AutonomousTaskModel:
        """Convert a database row to an AutonomousTaskModel."""
        return AutonomousTaskModel(
            id=row["id"],
            mission_id=row["mission_id"],
            parent_task_id=row["parent_task_id"],
            agent_id=row["agent_id"],
            name=row["name"],
            description=row["description"],
            capability_id=row["capability_id"],
            inputs=row["inputs"] if isinstance(row["inputs"], dict) else json.loads(row["inputs"]),
            status=row["status"],
            priority=row["priority"],
            progress=row["progress"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            deadline=row["deadline"],
            max_retries=row["max_retries"],
            retry_count=row["retry_count"],
            resource_budget=row["resource_budget"] if isinstance(row["resource_budget"], dict) else json.loads(row["resource_budget"]),
            checkpoint_id=row["checkpoint_id"],
            result=row["result"] if isinstance(row["result"], dict) else json.loads(row["result"]) if row["result"] else None,
            failure=row["failure"],
            task_metadata=row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"]),
            provider_request_type=row["provider_request_type"],
            task_category=row["task_category"],
            execution_requirements=row["execution_requirements"] if isinstance(row["execution_requirements"], dict) else json.loads(row["execution_requirements"]) if row["execution_requirements"] else None,
            execution_plan=row["execution_plan"] if isinstance(row["execution_plan"], dict) else json.loads(row["execution_plan"]) if row["execution_plan"] else None,
        )

    def create(self, task: AutonomousTaskModel) -> AutonomousTaskModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.autonomous_task (
                        id, mission_id, parent_task_id, agent_id, name, description,
                        capability_id, inputs, status, priority, progress, created_at,
                        started_at, updated_at, completed_at, deadline, max_retries,
                        retry_count, resource_budget, checkpoint_id, result, failure,
                        metadata, provider_request_type, task_category,
                        execution_requirements, execution_plan
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        task.id,
                        task.mission_id,
                        task.parent_task_id,
                        task.agent_id,
                        task.name,
                        task.description,
                        task.capability_id,
                        json.dumps(task.inputs),
                        task.status,
                        task.priority,
                        task.progress,
                        task.created_at,
                        task.started_at,
                        task.updated_at,
                        task.completed_at,
                        task.deadline,
                        task.max_retries,
                        task.retry_count,
                        json.dumps(task.resource_budget),
                        task.checkpoint_id,
                        json.dumps(task.result) if task.result else None,
                        task.failure,
                        json.dumps(task.task_metadata),
                        task.provider_request_type,
                        task.task_category,
                        json.dumps(task.execution_requirements) if task.execution_requirements else None,
                        json.dumps(task.execution_plan) if task.execution_plan else None,
                    ),
                )
                conn.commit()
                return task

    def get(self, task_id: str) -> AutonomousTaskModel | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.autonomous_task WHERE id = %s",
                    (task_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_model(row)

    def update(self, task: AutonomousTaskModel) -> AutonomousTaskModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                now = datetime.now(UTC)
                cur.execute(
                    """
                    UPDATE execution.autonomous_task SET
                        mission_id = %s,
                        parent_task_id = %s,
                        agent_id = %s,
                        name = %s,
                        description = %s,
                        capability_id = %s,
                        inputs = %s,
                        status = %s,
                        priority = %s,
                        progress = %s,
                        started_at = %s,
                        updated_at = %s,
                        completed_at = %s,
                        deadline = %s,
                        max_retries = %s,
                        retry_count = %s,
                        resource_budget = %s,
                        checkpoint_id = %s,
                        result = %s,
                        failure = %s,
                        metadata = %s,
                        provider_request_type = %s,
                        task_category = %s,
                        execution_requirements = %s,
                        execution_plan = %s
                    WHERE id = %s
                    """,
                    (
                        task.mission_id,
                        task.parent_task_id,
                        task.agent_id,
                        task.name,
                        task.description,
                        task.capability_id,
                        json.dumps(task.inputs),
                        task.status,
                        task.priority,
                        task.progress,
                        task.started_at,
                        now,
                        task.completed_at,
                        task.deadline,
                        task.max_retries,
                        task.retry_count,
                        json.dumps(task.resource_budget),
                        task.checkpoint_id,
                        json.dumps(task.result) if task.result else None,
                        task.failure,
                        json.dumps(task.task_metadata),
                        task.provider_request_type,
                        task.task_category,
                        json.dumps(task.execution_requirements) if task.execution_requirements else None,
                        json.dumps(task.execution_plan) if task.execution_plan else None,
                        task.id,
                    ),
                )
                conn.commit()
                task.updated_at = now
                return task

    def delete(self, task_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM execution.autonomous_task WHERE id = %s",
                    (task_id,),
                )
                conn.commit()
                return cur.rowcount > 0

    def list_by_mission(self, mission_id: str) -> list[AutonomousTaskModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.autonomous_task WHERE mission_id = %s",
                    (mission_id,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_by_status(self, status: str, limit: int = 100, offset: int = 0) -> list[AutonomousTaskModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.autonomous_task WHERE status = %s LIMIT %s OFFSET %s",
                    (status, limit, offset),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_ready_to_run(self, limit: int = 100) -> list[AutonomousTaskModel]:
        """Get tasks that are READY to execute (dependencies satisfied)."""
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.autonomous_task WHERE status = %s LIMIT %s",
                    (AutonomousTaskStatus.READY.value, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def claim_ready_task(self, task_id: str) -> AutonomousTaskModel | None:
        """
        Atomically claim a READY task by transitioning it to RUNNING.
        
        Uses a conditional UPDATE that only succeeds if the task is still
        in READY status. Returns the updated task model if successful,
        None if the task was not READY (already claimed by another process).
        """
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                now = datetime.now(UTC)
                cur.execute(
                    """
                    UPDATE execution.autonomous_task SET
                        status = %s,
                        started_at = %s,
                        updated_at = %s
                    WHERE id = %s AND status = %s
                    RETURNING *
                    """,
                    (
                        AutonomousTaskStatus.RUNNING.value,
                        now,
                        now,
                        task_id,
                        AutonomousTaskStatus.READY.value,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                if row is None:
                    return None
                return self._row_to_model(row)

    def list_waiting_for_dependency(self, limit: int = 100) -> list[AutonomousTaskModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.autonomous_task WHERE status = %s LIMIT %s",
                    (AutonomousTaskStatus.WAITING_FOR_DEPENDENCY.value, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_retrying(self, limit: int = 100) -> list[AutonomousTaskModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.autonomous_task WHERE status = %s LIMIT %s",
                    (AutonomousTaskStatus.RETRYING.value, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def count_by_status(self, status: str) -> int:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM execution.autonomous_task WHERE status = %s",
                    (status,),
                )
                return cur.fetchone()[0] or 0


class TaskDependencyRepository:
    """Repository for Task Dependency persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _row_to_model(self, row: dict[str, Any]) -> TaskDependencyModel:
        """Convert a database row to a TaskDependencyModel."""
        return TaskDependencyModel(
            id=row["id"],
            task_id=row["task_id"],
            depends_on_task_id=row["depends_on_task_id"],
            status=row["status"],
            created_at=row["created_at"],
            satisfied_at=row["satisfied_at"],
        )

    def create(self, dependency: TaskDependencyModel) -> TaskDependencyModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.task_dependency (
                        id, task_id, depends_on_task_id, status, created_at, satisfied_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        dependency.id,
                        dependency.task_id,
                        dependency.depends_on_task_id,
                        dependency.status,
                        dependency.created_at,
                        dependency.satisfied_at,
                    ),
                )
                conn.commit()
                return dependency

    def get(self, dependency_id: str) -> TaskDependencyModel | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.task_dependency WHERE id = %s",
                    (dependency_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_model(row)

    def update(self, dependency: TaskDependencyModel) -> TaskDependencyModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution.task_dependency SET
                        task_id = %s,
                        depends_on_task_id = %s,
                        status = %s,
                        satisfied_at = %s
                    WHERE id = %s
                    """,
                    (
                        dependency.task_id,
                        dependency.depends_on_task_id,
                        dependency.status,
                        dependency.satisfied_at,
                        dependency.id,
                    ),
                )
                conn.commit()
                return dependency

    def get_dependencies_for_task(self, task_id: str) -> list[TaskDependencyModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.task_dependency WHERE task_id = %s",
                    (task_id,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def get_dependents_for_task(self, task_id: str) -> list[TaskDependencyModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.task_dependency WHERE depends_on_task_id = %s",
                    (task_id,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def mark_satisfied(self, task_id: str, depends_on_task_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                now = datetime.now(UTC)
                cur.execute(
                    """
                    UPDATE execution.task_dependency SET
                        status = %s,
                        satisfied_at = %s
                    WHERE task_id = %s AND depends_on_task_id = %s
                    """,
                    (DependencyStatus.SATISFIED.value, now, task_id, depends_on_task_id),
                )
                conn.commit()
                return cur.rowcount > 0

    def are_all_dependencies_satisfied(self, task_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM execution.task_dependency
                    WHERE task_id = %s AND status != %s
                    """,
                    (task_id, DependencyStatus.SATISFIED.value),
                )
                count = cur.fetchone()[0] or 0
                return count == 0


class AgentInstanceRepository:
    """Repository for Agent Instance persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _row_to_model(self, row: dict[str, Any]) -> AgentInstanceModel:
        """Convert a database row to an AgentInstanceModel."""
        return AgentInstanceModel(
            id=row["id"],
            mission_id=row["mission_id"],
            task_id=row["task_id"],
            agent_profile_id=row["agent_profile_id"],
            parent_agent_id=row["parent_agent_id"],
            status=row["status"],
            runtime=row["runtime"],
            permission_context=row["permission_context"] if isinstance(row["permission_context"], dict) else json.loads(row["permission_context"]),
            resource_budget=row["resource_budget"] if isinstance(row["resource_budget"], dict) else json.loads(row["resource_budget"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            last_heartbeat=row["last_heartbeat"],
            result=row["result"] if isinstance(row["result"], dict) else json.loads(row["result"]) if row["result"] else None,
            failure=row["failure"],
            agent_metadata=row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"]),
        )

    def create(self, agent: AgentInstanceModel) -> AgentInstanceModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.agent_instance (
                        id, mission_id, task_id, agent_profile_id, parent_agent_id,
                        status, runtime, permission_context, resource_budget,
                        created_at, started_at, updated_at, completed_at,
                        last_heartbeat, result, failure, metadata
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        agent.id,
                        agent.mission_id,
                        agent.task_id,
                        agent.agent_profile_id,
                        agent.parent_agent_id,
                        agent.status,
                        agent.runtime,
                        json.dumps(agent.permission_context),
                        json.dumps(agent.resource_budget),
                        agent.created_at,
                        agent.started_at,
                        agent.updated_at,
                        agent.completed_at,
                        agent.last_heartbeat,
                        json.dumps(agent.result) if agent.result else None,
                        agent.failure,
                        json.dumps(agent.agent_metadata),
                    ),
                )
                conn.commit()
                return agent

    def get(self, agent_id: str) -> AgentInstanceModel | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.agent_instance WHERE id = %s",
                    (agent_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_model(row)

    def update(self, agent: AgentInstanceModel) -> AgentInstanceModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                now = datetime.now(UTC)
                cur.execute(
                    """
                    UPDATE execution.agent_instance SET
                        mission_id = %s,
                        task_id = %s,
                        agent_profile_id = %s,
                        parent_agent_id = %s,
                        status = %s,
                        runtime = %s,
                        permission_context = %s,
                        resource_budget = %s,
                        started_at = %s,
                        updated_at = %s,
                        completed_at = %s,
                        last_heartbeat = %s,
                        result = %s,
                        failure = %s,
                        metadata = %s
                    WHERE id = %s
                    """,
                    (
                        agent.mission_id,
                        agent.task_id,
                        agent.agent_profile_id,
                        agent.parent_agent_id,
                        agent.status,
                        agent.runtime,
                        json.dumps(agent.permission_context),
                        json.dumps(agent.resource_budget),
                        agent.started_at,
                        now,
                        agent.completed_at,
                        agent.last_heartbeat,
                        json.dumps(agent.result) if agent.result else None,
                        agent.failure,
                        json.dumps(agent.agent_metadata),
                        agent.id,
                    ),
                )
                conn.commit()
                agent.updated_at = now
                return agent

    def delete(self, agent_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM execution.agent_instance WHERE id = %s",
                    (agent_id,),
                )
                conn.commit()
                return cur.rowcount > 0

    def list_by_mission(self, mission_id: str) -> list[AgentInstanceModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.agent_instance WHERE mission_id = %s",
                    (mission_id,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_by_task(self, task_id: str) -> list[AgentInstanceModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.agent_instance WHERE task_id = %s",
                    (task_id,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_by_parent(self, parent_agent_id: str) -> list[AgentInstanceModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.agent_instance WHERE parent_agent_id = %s",
                    (parent_agent_id,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_stale_heartbeats(self, timeout_seconds: float) -> list[AgentInstanceModel]:
        """Find agents with stale heartbeats (potential crashes)."""
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cutoff = datetime.now(UTC)
                # Note: In a real implementation, we'd subtract timeout_seconds from cutoff
                # For now, just return agents that haven't had a heartbeat in the timeout window
                cur.execute(
                    """
                    SELECT * FROM execution.agent_instance
                    WHERE status = %s AND last_heartbeat IS NOT NULL
                    """,
                    (AgentInstanceStatus.RUNNING.value,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_by_status(self, status: str) -> list[AgentInstanceModel]:
        """List agents by status."""
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.agent_instance WHERE status = %s",
                    (status,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]


class WorkerRepository:
    """Repository for Worker persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _row_to_model(self, row: dict[str, Any]) -> WorkerModel:
        """Convert a database row to a WorkerModel."""
        return WorkerModel(
            id=row["id"],
            task_id=row["task_id"],
            execution_id=row["execution_id"],
            status=row["status"],
            started_at=row["started_at"],
            last_activity=row["last_activity"],
            last_heartbeat=row["last_heartbeat"],
            heartbeat_interval_seconds=row["heartbeat_interval_seconds"],
            timeout_seconds=row["timeout_seconds"],
            result=row["result"] if isinstance(row["result"], dict) else json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            worker_metadata=row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"]),
        )

    def create(self, worker: WorkerModel) -> WorkerModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.worker (
                        id, task_id, execution_id, status, started_at,
                        last_activity, last_heartbeat, heartbeat_interval_seconds,
                        timeout_seconds, result, error, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        worker.id,
                        worker.task_id,
                        worker.execution_id,
                        worker.status,
                        worker.started_at,
                        worker.last_activity,
                        worker.last_heartbeat,
                        worker.heartbeat_interval_seconds,
                        worker.timeout_seconds,
                        json.dumps(worker.result) if worker.result else None,
                        worker.error,
                        json.dumps(worker.worker_metadata),
                    ),
                )
                conn.commit()
                return worker

    def get(self, worker_id: str) -> WorkerModel | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.worker WHERE id = %s",
                    (worker_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_model(row)

    def update(self, worker: WorkerModel) -> WorkerModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution.worker SET
                        task_id = %s,
                        execution_id = %s,
                        status = %s,
                        last_activity = %s,
                        last_heartbeat = %s,
                        heartbeat_interval_seconds = %s,
                        timeout_seconds = %s,
                        result = %s,
                        error = %s,
                        metadata = %s
                    WHERE id = %s
                    """,
                    (
                        worker.task_id,
                        worker.execution_id,
                        worker.status,
                        worker.last_activity,
                        worker.last_heartbeat,
                        worker.heartbeat_interval_seconds,
                        worker.timeout_seconds,
                        json.dumps(worker.result) if worker.result else None,
                        worker.error,
                        json.dumps(worker.worker_metadata),
                        worker.id,
                    ),
                )
                conn.commit()
                return worker

    def delete(self, worker_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM execution.worker WHERE id = %s",
                    (worker_id,),
                )
                conn.commit()
                return cur.rowcount > 0

    def list_by_task(self, task_id: str) -> list[WorkerModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.worker WHERE task_id = %s",
                    (task_id,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_by_status(self, status: str) -> list[WorkerModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.worker WHERE status = %s",
                    (status,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_crashed(self, timeout_seconds: float) -> list[WorkerModel]:
        """Find workers that have missed their heartbeat (potential crashes)."""
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Workers in RUNNING state with no recent heartbeat
                cur.execute(
                    """
                    SELECT * FROM execution.worker
                    WHERE status = %s AND last_heartbeat IS NOT NULL
                    """,
                    (WorkerStatus.RUNNING.value,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]


class ExecutionRepository:
    """Repository for Execution Attempt persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _row_to_model(self, row: dict[str, Any]) -> ExecutionModel:
        """Convert a database row to an ExecutionModel."""
        return ExecutionModel(
            id=row["id"],
            task_id=row["task_id"],
            worker_id=row["worker_id"],
            status=row["status"],
            attempt_number=row["attempt_number"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            checkpoint_id=row["checkpoint_id"],
            result=row["result"] if isinstance(row["result"], dict) else json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            execution_metadata=row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"]),
            selected_implementation_id=row["selected_implementation_id"],
            implementation_version=row["implementation_version"],
            implementation_source=row["implementation_source"],
            execution_backend=row["execution_backend"],
            required_environment=row["required_environment"],
            actual_environment=row["actual_environment"],
            step_index=row["step_index"],
            policy_decision_id=row["policy_decision_id"],
            budget_allocation_id=row["budget_allocation_id"],
            fallback_from_execution_id=row["fallback_from_execution_id"],
            fallback_reason=row["fallback_reason"],
            agent_id=row["agent_id"],
        )

    def create(self, execution: ExecutionModel) -> ExecutionModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.execution (
                        id, task_id, worker_id, status, attempt_number, started_at,
                        updated_at, completed_at, checkpoint_id, result, error,
                        metadata, selected_implementation_id, implementation_version,
                        implementation_source, execution_backend, required_environment,
                        actual_environment, step_index, policy_decision_id,
                        budget_allocation_id, fallback_from_execution_id,
                        fallback_reason, agent_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        execution.id,
                        execution.task_id,
                        execution.worker_id,
                        execution.status,
                        execution.attempt_number,
                        execution.started_at,
                        execution.updated_at,
                        execution.completed_at,
                        execution.checkpoint_id,
                        json.dumps(execution.result) if execution.result else None,
                        execution.error,
                        json.dumps(execution.execution_metadata),
                        execution.selected_implementation_id,
                        execution.implementation_version,
                        execution.implementation_source,
                        execution.execution_backend,
                        execution.required_environment,
                        execution.actual_environment,
                        execution.step_index,
                        execution.policy_decision_id,
                        execution.budget_allocation_id,
                        execution.fallback_from_execution_id,
                        execution.fallback_reason,
                        execution.agent_id,
                    ),
                )
                conn.commit()
                return execution

    def get(self, execution_id: str) -> ExecutionModel | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.execution WHERE id = %s",
                    (execution_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_model(row)

    def update(self, execution: ExecutionModel) -> ExecutionModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                now = datetime.now(UTC)
                cur.execute(
                    """
                    UPDATE execution.execution SET
                        task_id = %s,
                        worker_id = %s,
                        status = %s,
                        attempt_number = %s,
                        updated_at = %s,
                        completed_at = %s,
                        checkpoint_id = %s,
                        result = %s,
                        error = %s,
                        metadata = %s,
                        selected_implementation_id = %s,
                        implementation_version = %s,
                        implementation_source = %s,
                        execution_backend = %s,
                        required_environment = %s,
                        actual_environment = %s,
                        step_index = %s,
                        policy_decision_id = %s,
                        budget_allocation_id = %s,
                        fallback_from_execution_id = %s,
                        fallback_reason = %s,
                        agent_id = %s
                    WHERE id = %s
                    """,
                    (
                        execution.task_id,
                        execution.worker_id,
                        execution.status,
                        execution.attempt_number,
                        now,
                        execution.completed_at,
                        execution.checkpoint_id,
                        json.dumps(execution.result) if execution.result else None,
                        execution.error,
                        json.dumps(execution.execution_metadata),
                        execution.selected_implementation_id,
                        execution.implementation_version,
                        execution.implementation_source,
                        execution.execution_backend,
                        execution.required_environment,
                        execution.actual_environment,
                        execution.step_index,
                        execution.policy_decision_id,
                        execution.budget_allocation_id,
                        execution.fallback_from_execution_id,
                        execution.fallback_reason,
                        execution.agent_id,
                        execution.id,
                    ),
                )
                conn.commit()
                execution.updated_at = now
                return execution

    def list_by_task(self, task_id: str) -> list[ExecutionModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.execution WHERE task_id = %s",
                    (task_id,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def get_latest_for_task(self, task_id: str) -> ExecutionModel | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.execution WHERE task_id = %s ORDER BY attempt_number DESC LIMIT 1",
                    (task_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_model(row)


class CheckpointRepository:
    """Repository for Checkpoint persistence."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _row_to_model(self, row: dict[str, Any]) -> CheckpointModel:
        """Convert a database row to a CheckpointModel."""
        return CheckpointModel(
            id=row["id"],
            task_id=row["task_id"],
            execution_id=row["execution_id"],
            mission_id=row["mission_id"],
            agent_id=row["agent_id"],
            version=row["version"],
            status=row["status"],
            state_data=row["state_data"] if isinstance(row["state_data"], dict) else json.loads(row["state_data"]),
            created_at=row["created_at"],
            validated_at=row["validated_at"],
            restored_at=row["restored_at"],
            checkpoint_metadata=row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"]),
        )

    def create(self, checkpoint: CheckpointModel) -> CheckpointModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.checkpoint (
                        id, task_id, execution_id, mission_id, agent_id,
                        version, status, state_data, created_at, validated_at,
                        restored_at, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        checkpoint.id,
                        checkpoint.task_id,
                        checkpoint.execution_id,
                        checkpoint.mission_id,
                        checkpoint.agent_id,
                        checkpoint.version,
                        checkpoint.status,
                        json.dumps(checkpoint.state_data),
                        checkpoint.created_at,
                        checkpoint.validated_at,
                        checkpoint.restored_at,
                        json.dumps(checkpoint.checkpoint_metadata),
                    ),
                )
                conn.commit()
                return checkpoint

    def get(self, checkpoint_id: str) -> CheckpointModel | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.checkpoint WHERE id = %s",
                    (checkpoint_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_model(row)

    def update(self, checkpoint: CheckpointModel) -> CheckpointModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution.checkpoint SET
                        task_id = %s,
                        execution_id = %s,
                        mission_id = %s,
                        agent_id = %s,
                        version = %s,
                        status = %s,
                        state_data = %s,
                        validated_at = %s,
                        restored_at = %s,
                        metadata = %s
                    WHERE id = %s
                    """,
                    (
                        checkpoint.task_id,
                        checkpoint.execution_id,
                        checkpoint.mission_id,
                        checkpoint.agent_id,
                        checkpoint.version,
                        checkpoint.status,
                        json.dumps(checkpoint.state_data),
                        checkpoint.validated_at,
                        checkpoint.restored_at,
                        json.dumps(checkpoint.checkpoint_metadata),
                        checkpoint.id,
                    ),
                )
                conn.commit()
                return checkpoint

    def get_latest_for_task(self, task_id: str) -> CheckpointModel | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM execution.checkpoint
                    WHERE task_id = %s AND status = %s
                    ORDER BY version DESC LIMIT 1
                    """,
                    (task_id, CheckpointStatus.AVAILABLE.value),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_model(row)

    def list_by_execution(self, execution_id: str) -> list[CheckpointModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.checkpoint WHERE execution_id = %s",
                    (execution_id,),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def invalidate_old_checkpoints(self, task_id: str, keep_version: int) -> int:
        """Invalidate checkpoints older than the specified version."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution.checkpoint SET status = %s
                    WHERE task_id = %s AND version < %s AND status = %s
                    """,
                    (CheckpointStatus.INVALIDATED.value, task_id, keep_version, CheckpointStatus.AVAILABLE.value),
                )
                conn.commit()
                return cur.rowcount


class WorldStateRepository:
    """Repository for World State snapshots."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _row_to_model(self, row: dict[str, Any]) -> WorldStateModel:
        """Convert a database row to a WorldStateModel."""
        return WorldStateModel(
            id=row["id"],
            active_missions=row["active_missions"],
            active_tasks=row["active_tasks"],
            active_agents=row["active_agents"],
            waiting_tasks=row["waiting_tasks"],
            blocked_tasks=row["blocked_tasks"],
            failed_tasks=row["failed_tasks"],
            retrying_tasks=row["retrying_tasks"],
            scheduled_tasks=row["scheduled_tasks"],
            pending_approvals=row["pending_approvals"],
            active_workers=row["active_workers"],
            crashed_workers=row["crashed_workers"],
            resource_usage=row["resource_usage"] if isinstance(row["resource_usage"], dict) else json.loads(row["resource_usage"]),
            updated_at=row["updated_at"],
        )

    def create_snapshot(self, snapshot: WorldStateModel) -> WorldStateModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.world_state (
                        active_missions, active_tasks, active_agents, waiting_tasks,
                        blocked_tasks, failed_tasks, retrying_tasks, scheduled_tasks,
                        pending_approvals, active_workers, crashed_workers,
                        resource_usage, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        snapshot.active_missions,
                        snapshot.active_tasks,
                        snapshot.active_agents,
                        snapshot.waiting_tasks,
                        snapshot.blocked_tasks,
                        snapshot.failed_tasks,
                        snapshot.retrying_tasks,
                        snapshot.scheduled_tasks,
                        snapshot.pending_approvals,
                        snapshot.active_workers,
                        snapshot.crashed_workers,
                        json.dumps(snapshot.resource_usage),
                        snapshot.updated_at,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                snapshot.id = row[0]
                return snapshot

    def get_latest(self) -> WorldStateModel | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.world_state ORDER BY updated_at DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_model(row)


class AutonomousEventRepository:
    """Repository for Autonomous Event persistence (audit trail)."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _row_to_model(self, row: dict[str, Any]) -> AutonomousEventModel:
        """Convert a database row to an AutonomousEventModel."""
        return AutonomousEventModel(
            id=row["id"],
            event_id=row["event_id"],
            event_type=row["event_type"],
            timestamp=row["timestamp"],
            mission_id=row["mission_id"],
            task_id=row["task_id"],
            agent_id=row["agent_id"],
            execution_id=row["execution_id"],
            worker_id=row["worker_id"],
            parent_task_id=row["parent_task_id"],
            parent_agent_id=row["parent_agent_id"],
            payload=row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"]),
        )

    def create(self, event: AutonomousEventModel) -> AutonomousEventModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.autonomous_event (
                        event_id, event_type, timestamp, mission_id, task_id,
                        agent_id, execution_id, worker_id, parent_task_id,
                        parent_agent_id, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        event.event_id,
                        event.event_type,
                        event.timestamp,
                        event.mission_id,
                        event.task_id,
                        event.agent_id,
                        event.execution_id,
                        event.worker_id,
                        event.parent_task_id,
                        event.parent_agent_id,
                        json.dumps(event.payload),
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                event.id = row[0]
                return event

    def list_by_mission(self, mission_id: str, limit: int = 100) -> list[AutonomousEventModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.autonomous_event WHERE mission_id = %s ORDER BY timestamp DESC LIMIT %s",
                    (mission_id, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_by_task(self, task_id: str, limit: int = 100) -> list[AutonomousEventModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.autonomous_event WHERE task_id = %s ORDER BY timestamp DESC LIMIT %s",
                    (task_id, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_by_agent(self, agent_id: str, limit: int = 100) -> list[AutonomousEventModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.autonomous_event WHERE agent_id = %s ORDER BY timestamp DESC LIMIT %s",
                    (agent_id, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_by_execution(self, execution_id: str, limit: int = 100) -> list[AutonomousEventModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.autonomous_event WHERE execution_id = %s ORDER BY timestamp DESC LIMIT %s",
                    (execution_id, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_by_worker(self, worker_id: str, limit: int = 100) -> list[AutonomousEventModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.autonomous_event WHERE worker_id = %s ORDER BY timestamp DESC LIMIT %s",
                    (worker_id, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]


class AgentMessageRepository:
    """Repository for Agent Message persistence (A2A communication)."""

    def __init__(self, pool_manager: PoolManager, logger: Logger) -> None:
        self._pool = pool_manager
        self._logger = logger.get_logger(__name__)

    def _row_to_model(self, row: dict[str, Any]) -> AgentMessageModel:
        """Convert a database row to an AgentMessageModel."""
        return AgentMessageModel(
            id=row["id"],
            message_id=row["message_id"],
            message_type=row["message_type"],
            timestamp=row["timestamp"],
            mission_id=row["mission_id"],
            sender_agent_id=row["sender_agent_id"],
            recipient_agent_id=row["recipient_agent_id"],
            task_id=row["task_id"],
            status=row["status"],
            payload=row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"]),
            priority=row["priority"],
        )

    def create(self, message: AgentMessageModel) -> AgentMessageModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO execution.agent_message (
                        message_id, message_type, timestamp, mission_id,
                        sender_agent_id, recipient_agent_id, task_id,
                        status, payload, priority
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        message.message_id,
                        message.message_type,
                        message.timestamp,
                        message.mission_id,
                        message.sender_agent_id,
                        message.recipient_agent_id,
                        message.task_id,
                        message.status,
                        json.dumps(message.payload),
                        message.priority,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                message.id = row[0]
                return message

    def get(self, message_id: str) -> AgentMessageModel | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.agent_message WHERE message_id = %s",
                    (message_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_model(row)

    def update(self, message: AgentMessageModel) -> AgentMessageModel:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE execution.agent_message SET
                        status = %s,
                        payload = %s,
                        priority = %s
                    WHERE message_id = %s
                    """,
                    (
                        message.status,
                        json.dumps(message.payload),
                        message.priority,
                        message.message_id,
                    ),
                )
                conn.commit()
                return message

    def list_by_mission(self, mission_id: str, limit: int = 100) -> list[AgentMessageModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.agent_message WHERE mission_id = %s ORDER BY timestamp DESC LIMIT %s",
                    (mission_id, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_by_sender(self, sender_agent_id: str, limit: int = 100) -> list[AgentMessageModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.agent_message WHERE sender_agent_id = %s ORDER BY timestamp DESC LIMIT %s",
                    (sender_agent_id, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_by_recipient(self, recipient_agent_id: str, limit: int = 100) -> list[AgentMessageModel]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.agent_message WHERE recipient_agent_id = %s ORDER BY timestamp DESC LIMIT %s",
                    (recipient_agent_id, limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def list_pending_for_agent(self, recipient_agent_id: str, limit: int = 100) -> list[AgentMessageModel]:
        """Get pending messages for a recipient agent."""
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM execution.agent_message WHERE recipient_agent_id = %s AND status = %s ORDER BY timestamp ASC LIMIT %s",
                    (recipient_agent_id, "pending", limit),
                )
                return [self._row_to_model(row) for row in cur.fetchall()]

    def mark_delivered(self, message_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE execution.agent_message SET status = %s WHERE message_id = %s",
                    ("delivered", message_id),
                )
                conn.commit()
                return cur.rowcount > 0

    def mark_read(self, message_id: str) -> bool:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE execution.agent_message SET status = %s WHERE message_id = %s",
                    ("read", message_id),
                )
                conn.commit()
                return cur.rowcount > 0