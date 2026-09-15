"""
Tests for AutonomousTaskManager - task creation and lifecycle transitions.
"""

from datetime import UTC, datetime
from types import MappingProxyType
from unittest.mock import MagicMock, Mock

import pytest

from parika.core.autonomous import (
    AutonomousTaskStatus,
)
from parika.core.autonomous.repository import AutonomousTaskRepository
from parika.core.autonomous.task_manager import AutonomousTaskManager
from parika.core.database.pool import PoolManager
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.configuration.configuration import Configuration


class TestAutonomousTaskManager:
    """Tests for AutonomousTaskManager."""

    def _make_task_manager(self):
        """Create a task manager with mocked dependencies."""
        # Mock pool and logger
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=None)
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_conn.commit = MagicMock()

        mock_logger = Mock(spec=Logger)
        mock_logger.get_logger = Mock(return_value=Mock(info=Mock(), debug=Mock(), warning=Mock(), error=Mock()))
        mock_event_bus = Mock(spec=EventBus)
        mock_dep_repo = Mock()
        mock_dep_repo.get_dependents_for_task = Mock(return_value=[])
        mock_dep_repo.are_all_dependencies_satisfied = Mock(return_value=True)
        mock_dep_repo.mark_satisfied = Mock()

        repo = AutonomousTaskRepository(mock_pool, mock_logger)
        task_manager = AutonomousTaskManager(
            repository=repo,
            dependency_repository=mock_dep_repo,
            event_bus=mock_event_bus,
            logger=mock_logger,
        )
        return task_manager, mock_pool, mock_logger, mock_event_bus, mock_dep_repo

    def test_create_root_task_becomes_ready(self):
        """Test that a root task (no dependencies) transitions to READY immediately."""
        task_manager, _, _, _, _ = self._make_task_manager()

        task = task_manager.create(
            mission_id="mission-1",
            name="Root Task",
            description="Test root task",
            capability_id="filesystem.exists",
            inputs=MappingProxyType({"path": "/test"}),
            depends_on=(),  # No dependencies - root task
        )

        # Root task should transition: CREATED -> SCHEDULED -> READY
        assert task.status == AutonomousTaskStatus.READY

    def test_create_dependent_task_waits_for_dependency(self):
        """Test that a task with dependencies stays at WAITING_FOR_DEPENDENCY."""
        task_manager, _, _, _, _ = self._make_task_manager()

        # Create root task first
        root_task = task_manager.create(
            mission_id="mission-1",
            name="Root Task",
            description="Test root task",
            capability_id="filesystem.exists",
            inputs=MappingProxyType({"path": "/test"}),
            depends_on=(),
        )

        # Create dependent task
        dependent_task = task_manager.create(
            mission_id="mission-1",
            name="Dependent Task",
            description="Test dependent task",
            capability_id="chat.respond",
            inputs=MappingProxyType({"message": "Summarize"}),
            depends_on=(root_task.id,),  # Has dependency
        )

        # Dependent task should be WAITING_FOR_DEPENDENCY
        assert dependent_task.status == AutonomousTaskStatus.WAITING_FOR_DEPENDENCY

    def test_root_task_logs_status(self):
        """Test that root task creation logs the final status."""
        task_manager, _, mock_logger, _, _ = self._make_task_manager()

        task = task_manager.create(
            mission_id="mission-1",
            name="Root Task",
            description="Test root task",
            capability_id="filesystem.exists",
            inputs=MappingProxyType({"path": "/test"}),
            depends_on=(),
        )

        # Verify final status is READY
        assert task.status == AutonomousTaskStatus.READY

        # Verify logger was called with status in the log
        log_calls = mock_logger.get_logger.return_value.info.call_args_list
        # Last call should be the formatted log with status
        last_log_call = log_calls[-1]
        # The call args are (format_string, task_id, mission_id, status_value)
        format_string, *args = last_log_call[0]
        # The third arg should be the status value
        assert task.status.value == args[2]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])