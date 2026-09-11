"""
Tests for Recovery integration.
"""

from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from unittest.mock import Mock, MagicMock, patch, call, ANY
from uuid import uuid4

import pytest

from parika.core.autonomous import (
    AutonomousTaskStatus,
    WorkerStatus,
    RecoveryAction,
)
from parika.core.autonomous.models import (
    MissionModel,
    AutonomousTaskModel,
    WorkerModel,
)
from parika.core.autonomous.recovery_coordinator import RecoveryCoordinator


class TestRecoveryIntegration:
    """Tests for recovery coordinator integration."""

    def _make_recovery_coordinator(self):
        """Create a recovery coordinator with mocked repositories."""
        mock_mission_repo = Mock()
        mock_task_repo = Mock()
        mock_dep_repo = Mock()
        mock_agent_repo = Mock()
        mock_worker_repo = Mock()
        mock_execution_repo = Mock()
        mock_checkpoint_manager = Mock()
        mock_event_bus = Mock()
        mock_logger = Mock()
        mock_logger.get_logger = Mock(return_value=Mock())

        coordinator = RecoveryCoordinator(
            mission_repository=mock_mission_repo,
            task_repository=mock_task_repo,
            dependency_repository=mock_dep_repo,
            agent_repository=mock_agent_repo,
            worker_repository=mock_worker_repo,
            execution_repository=mock_execution_repo,
            checkpoint_manager=mock_checkpoint_manager,
            event_bus=mock_event_bus,
            logger=Mock(),
        )

        return coordinator, mock_mission_repo, mock_task_repo, mock_dep_repo, mock_worker_repo, mock_execution_repo, mock_checkpoint_manager

    def test_recover_marks_crashed_workers(self):
        """Test recovery marks workers with stale heartbeats as crashed."""
        coordinator, mock_mission_repo, mock_task_repo, mock_dep_repo, mock_worker_repo, mock_execution_repo, mock_checkpoint_manager = self._make_recovery_coordinator()

        # Create a worker with stale heartbeat
        old_time = datetime.now(UTC) - timedelta(seconds=200)
        worker = WorkerModel(
            id="worker-1",
            task_id="task-1",
            execution_id="exec-1",
            status="running",
            started_at=datetime.now(UTC) - timedelta(hours=1),
            last_activity=old_time,
            last_heartbeat=old_time,
            heartbeat_interval_seconds=30.0,
            timeout_seconds=120.0,
        )

        updated_worker = {"worker": worker}

        def update_worker_side_effect(worker_model):
            updated_worker["worker"] = worker_model
            return worker_model

        mock_worker_repo.list_by_status = Mock(return_value=[worker])
        mock_worker_repo.update = Mock(side_effect=update_worker_side_effect)

        # Mock empty missions
        mock_mission_repo.list_active = Mock(return_value=[])
        mock_task_repo.list_by_status = Mock(return_value=[])
        mock_checkpoint_manager.get_latest_for_task = Mock(return_value=None)

        # Run recovery
        result = coordinator.recover()

        # Worker should be marked as crashed
        assert updated_worker["worker"].status == "crashed"
        assert result.workers_marked_crashed == 1

    def test_recover_running_task_with_checkpoint(self):
        """Test recovery restarts running task from checkpoint."""
        coordinator, mock_mission_repo, mock_task_repo, mock_dep_repo, mock_worker_repo, mock_execution_repo, mock_checkpoint_manager = self._make_recovery_coordinator()

        # Create a mission
        mission = MissionModel(
            id="mission-1",
            goal="Test mission",
            status="running",
            priority=0,
            created_at=datetime.now(UTC),
        )

        # Create a running task with crashed worker
        task = AutonomousTaskModel(
            id="task-1",
            mission_id="mission-1",
            name="Test Task",
            description="Test",
            capability_id="vision.provider_describe_image",
            inputs={},
            status="running",
            retry_count=0,
            max_retries=3,
            task_metadata={},
        )

        # Create a RUNNING worker with stale heartbeat (will be detected as crashed)
        worker = WorkerModel(
            id="worker-1",
            task_id="task-1",
            execution_id="exec-1",
            status="running",
            started_at=datetime.now(UTC) - timedelta(hours=1),
            last_activity=datetime.now(UTC) - timedelta(hours=1),
            last_heartbeat=datetime.now(UTC) - timedelta(seconds=200),
            heartbeat_interval_seconds=30.0,
            timeout_seconds=120.0,
        )

        updated_worker = {"worker": worker}

        def update_worker_side_effect(worker_model):
            updated_worker["worker"] = worker_model
            return worker_model

        mock_mission_repo.list_active = Mock(return_value=[mission])
        mock_task_repo.list_by_mission = Mock(return_value=[task])
        mock_task_repo.update = Mock(side_effect=update_task_side_effect)
        mock_worker_repo.list_by_task = Mock(return_value=[worker])
        mock_worker_repo.update = Mock(side_effect=update_worker_side_effect)
        mock_checkpoint_manager.get_latest_for_task = Mock(return_value=checkpoint)
        mock_checkpoint_manager.restore = Mock(return_value=checkpoint)

        # Mock dependencies
        coordinator._dependency_repository = Mock()
        coordinator._dependency_repository.are_all_dependencies_satisfied = Mock(return_value=True)

        result = coordinator.recover()

        # Task should be recovered
        assert updated_task["task"].status == "ready"
        assert updated_task["task"].checkpoint_id == "checkpoint-1"
        assert result.tasks_recovered == 1

    def test_recover_failed_task_with_retries(self):
        """Test recovery retries failed tasks within retry limit."""
        coordinator, mock_mission_repo, mock_task_repo, mock_dep_repo, mock_worker_repo, mock_execution_repo, mock_checkpoint_manager = self._make_recovery_coordinator()

        mission = MissionModel(
            id="mission-1",
            goal="Test mission",
            status="running",
            priority=0,
            created_at=datetime.now(UTC),
        )

        task = AutonomousTaskModel(
            id="task-1",
            mission_id="mission-1",
            name="Test Task",
            description="Test",
            capability_id="vision.provider_describe_image",
            inputs={},
            status="failed",
            retry_count=1,
            max_retries=3,
            task_metadata={},
        )

        updated_task = {"task": task}

        def update_task_side_effect(task_model):
            updated_task["task"] = task_model
            return task_model

        mock_mission_repo.list_active = Mock(return_value=[mission])
        mock_task_repo.list_by_mission = Mock(return_value=[task])
        mock_task_repo.update = Mock(side_effect=update_task_side_effect)
        mock_checkpoint_manager.get_latest_for_task = Mock(return_value=None)

        result = coordinator.recover()

        # Task should be marked for retry
        assert updated_task["task"].status == "retrying"
        assert updated_task["task"].retry_count == 2
        assert result.tasks_recovered == 1

    def test_recover_failed_task_exceeds_retries(self):
        """Test recovery marks failed task as cancelled when retries exceeded."""
        coordinator, mock_mission_repo, mock_task_repo, mock_dep_repo, mock_worker_repo, mock_execution_repo, mock_checkpoint_manager = self._make_recovery_coordinator()

        mission = MissionModel(
            id="mission-1",
            goal="Test mission",
            status="running",
            priority=0,
            created_at=datetime.now(UTC),
        )

        task = AutonomousTaskModel(
            id="task-1",
            mission_id="mission-1",
            name="Test Task",
            description="Test",
            capability_id="vision.provider_describe_image",
            inputs={},
            status="failed",
            retry_count=3,
            max_retries=3,
            task_metadata={},
        )

        updated_task = {"task": task}

        def update_task_side_effect(task_model):
            updated_task["task"] = task_model
            return task_model

        mock_mission_repo.list_active = Mock(return_value=[mission])
        mock_task_repo.list_by_mission = Mock(return_value=[task])
        mock_task_repo.update = Mock(side_effect=update_task_side_effect)
        mock_checkpoint_manager.get_latest_for_task = Mock(return_value=None)

        result = coordinator.recover()

        # Task should be marked as failed (cancelled in result)
        assert updated_task["task"].status == "failed"
        assert "Max retries exceeded" in updated_task["task"].failure
        assert result.tasks_cancelled == 1

    def test_recover_waiting_for_dependency_satisfied(self):
        """Test recovery promotes waiting tasks when dependencies satisfied."""
        coordinator, mock_mission_repo, mock_task_repo, mock_dep_repo, mock_worker_repo, mock_execution_repo, mock_checkpoint_manager = self._make_recovery_coordinator()

        mission = MissionModel(
            id="mission-1",
            goal="Test mission",
            status="running",
            priority=0,
            created_at=datetime.now(UTC),
        )

        task = AutonomousTaskModel(
            id="task-1",
            mission_id="mission-1",
            name="Test Task",
            description="Test",
            capability_id="vision.provider_describe_image",
            inputs={},
            status="waiting_for_dependency",
            task_metadata={},
        )

        updated_task = {"task": task}

        def update_task_side_effect(task_model):
            updated_task["task"] = task_model
            return task_model

        mock_mission_repo.list_active = Mock(return_value=[mission])
        mock_task_repo.list_by_mission = Mock(return_value=[task])
        mock_task_repo.update = Mock(side_effect=update_task_side_effect)
        mock_dep_repo.are_all_dependencies_satisfied = Mock(return_value=True)

        result = coordinator.recover()

        # Task should be promoted to READY
        assert updated_task["task"].status == "ready"
        assert result.tasks_recovered == 1

    def test_recovery_emits_events(self):
        """Test recovery emits appropriate events."""
        coordinator, mock_mission_repo, mock_task_repo, mock_dep_repo, mock_worker_repo, mock_execution_repo, mock_checkpoint_manager = self._make_recovery_coordinator()

        mock_mission_repo.list_active = Mock(return_value=[])
        mock_task_repo.list_by_status = Mock(return_value=[])
        mock_checkpoint_manager.get_latest_for_task = Mock(return_value=None)

        result = coordinator.recover()

        # Should emit recovery.completed event
        mock_event_bus = coordinator._event_bus
        mock_event_bus.publish.assert_any_call(
            "recovery.completed",
            ANY
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])