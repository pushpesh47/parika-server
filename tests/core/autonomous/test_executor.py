"""
Tests for AutonomousExecutor - executor logic and task claiming.
"""

from datetime import UTC, datetime
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import uuid4

import pytest

from parika.core.autonomous import (
    AutonomousExecutor,
    ExecutorConfig,
    AutonomousTaskStatus,
)
from parika.core.autonomous.contracts import AutonomousTaskStatus as ContractTaskStatus
from parika.core.autonomous.models import AutonomousTaskModel
from parika.core.planner.model_selection.requirements import ModelCapability


class TestExecutorConfig:
    """Tests for ExecutorConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ExecutorConfig()
        assert config.poll_interval_seconds == 5.0
        assert config.max_concurrent_tasks == 10
        assert config.checkpoint_interval_seconds == 30.0
        assert config.shutdown_timeout_seconds == 30.0

    def test_custom_config(self):
        """Test custom configuration values."""
        config = ExecutorConfig(
            poll_interval_seconds=10.0,
            max_concurrent_tasks=5,
            checkpoint_interval_seconds=60.0,
            shutdown_timeout_seconds=60.0,
        )
        assert config.poll_interval_seconds == 10.0
        assert config.max_concurrent_tasks == 5
        assert config.checkpoint_interval_seconds == 60.0
        assert config.shutdown_timeout_seconds == 60.0


class TestExecutorLifecycle:
    """Tests for executor start/stop lifecycle."""

    def _make_executor(self):
        """Create a minimal executor for testing."""
        mock_repo = Mock()
        mock_task_manager = Mock()
        mock_worker_manager = Mock()
        mock_checkpoint_manager = Mock()
        mock_capability_resolver = Mock()
        mock_planner = Mock()
        mock_capability_executor = Mock()
        mock_tool_manager = Mock()
        mock_provider_manager = Mock()
        mock_resource_manager = Mock()
        mock_policy_engine = Mock()
        mock_mission_manager = Mock()
        mock_authorization_boundary = Mock()
        mock_budget_enforcer = Mock()
        mock_agent_supervisor = Mock()
        mock_event_bus = Mock()
        mock_logger = Mock()
        mock_logger.get_logger = Mock(return_value=Mock())

        mock_repo.list_ready_to_run = Mock(return_value=[])
        mock_repo.claim_ready_task = Mock(return_value=None)

        executor = AutonomousExecutor(
            task_repository=mock_repo,
            task_manager=mock_task_manager,
            worker_manager=mock_worker_manager,
            checkpoint_manager=mock_checkpoint_manager,
            capability_resolver=mock_capability_resolver,
            planner=mock_planner,
            capability_executor=mock_capability_executor,
            tool_manager=mock_tool_manager,
            provider_manager=mock_provider_manager,
            resource_manager=mock_resource_manager,
            policy_engine=mock_policy_engine,
            mission_manager=mock_mission_manager,
            authorization_boundary=Mock(),
            budget_enforcer=Mock(),
            agent_supervisor=Mock(),
            event_bus=Mock(),
            logger=Mock(),
        )
        return executor, mock_repo, mock_task_manager, mock_worker_manager

    def test_start_stop(self):
        """Test executor start and stop."""
        executor, _, _, _ = self._make_executor()

        assert not executor._running
        executor.start()
        assert executor._running
        assert executor._thread is not None
        assert executor._thread.is_alive()

        executor.stop()
        assert not executor._running

    def test_double_start_idempotent(self):
        """Test that starting twice doesn't create two threads."""
        executor, _, _, _ = self._make_executor()

        executor.start()
        first_thread = executor._thread
        executor.start()
        assert executor._thread is first_thread

        executor.stop()

    def test_stop_when_not_running(self):
        """Test stopping when not running is no-op."""
        executor, _, _, _ = self._make_executor()

        assert not executor._running
        executor.stop()  # Should not raise
        assert not executor._running


class TestTaskClaiming:
    """Tests for atomic task claiming."""

    def test_claim_ready_task_success(self):
        """Test successful atomic claim of READY task."""
        from parika.core.autonomous import AutonomousTaskRepository
        from parika.core.autonomous.models import AutonomousTaskModel
        from parika.core.autonomous.contracts import AutonomousTaskStatus
        from unittest.mock import MagicMock

        # Mock the PoolManager and its connection context manager
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        
        # Set up the context manager chain: pool.connection() -> conn -> conn.cursor()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        
        # Mock cursor.fetchone to return a task row
        mock_row = {
            "id": "task-123",
            "mission_id": "mission-1",
            "parent_task_id": None,
            "agent_id": None,
            "name": "Test Task",
            "description": "Test",
            "capability_id": "vision.provider_describe_image",
            "inputs": {},
            "status": "running",  # After claiming, status is RUNNING
            "priority": 0,
            "progress": 0.0,
            "created_at": datetime.now(UTC),
            "started_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "completed_at": None,
            "deadline": None,
            "max_retries": 3,
            "retry_count": 0,
            "resource_budget": {},
            "checkpoint_id": None,
            "result": None,
            "failure": None,
            "metadata": {},
            "provider_request_type": None,
            "task_category": None,
            "execution_requirements": None,
            "execution_plan": None,
        }
        mock_cursor.fetchone.return_value = mock_row
        mock_conn.commit = MagicMock()

        from parika.core.database.pool import PoolManager
        repo = AutonomousTaskRepository(mock_pool, Mock())

        claimed = repo.claim_ready_task("task-123")

        assert claimed is not None
        assert claimed.id == "task-123"
        # Verify the UPDATE ... WHERE ... RETURNING pattern was used
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        assert "UPDATE execution.autonomous_task SET" in call_args[0][0]
        assert "WHERE id = %s AND status = %s" in call_args[0][0]
        assert "RETURNING *" in call_args[0][0]
        assert call_args[0][1][3] == "task-123"
        assert call_args[0][1][4] == AutonomousTaskStatus.READY.value
        mock_conn.commit.assert_called_once()


class TestToolExecutionPath:
    """Tests for TOOL capability execution path."""

    def test_tool_execution_builds_correct_request(self):
        """Test that TOOL execution builds correct ToolRequest and ExecutionTarget."""
        # This test verifies the executor builds the correct request structures
        # without actually executing the tool
        pass  # Implementation requires more extensive mocking


class TestProviderExecutionPath:
    """Tests for PROVIDER capability execution path."""

    def test_provider_execution_uses_planner(self):
        """Test that provider execution calls Planner.plan()."""
        # This test verifies the executor calls Planner.plan() for provider capabilities
        pass  # Implementation requires more extensive mocking


class TestTaskFailureHandling:
    """Tests for task failure and retry handling."""

    def test_failure_records_retry_in_budget(self):
        """Test that task failure records retry in budget enforcer."""
        pass  # Requires integration test setup


if __name__ == "__main__":
    pytest.main([__file__, "-v"])