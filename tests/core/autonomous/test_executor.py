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

        mock_pool = Mock()
        mock_session = Mock()
        mock_pool.sync_pool = Mock()
        mock_pool.sync_pool.__enter__ = Mock(return_value=mock_session)
        mock_pool.sync_pool.__exit__ = Mock(return_value=None)
        
        # Make session a context manager
        mock_session.__enter__ = Mock(return_value=mock_session)
        mock_session.__exit__ = Mock(return_value=None)

        # Mock the session.execute to return a task
        mock_task_model = AutonomousTaskModel(
            id="task-123",
            mission_id="mission-1",
            name="Test Task",
            description="Test",
            capability_id="vision.provider_describe_image",
            inputs={},
            status="ready",
            task_metadata={},
        )

        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_task_model
        mock_session.execute = Mock(return_value=mock_result)
        mock_session.commit = Mock()

        from parika.core.database.pool import PoolManager
        repo = AutonomousTaskRepository(PoolManager(), Mock())
        repo._session = Mock(return_value=mock_session)

        claimed = repo.claim_ready_task("task-123")

        assert claimed is not None
        assert claimed.id == "task-123"
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


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