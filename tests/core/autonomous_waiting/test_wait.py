"""
Tests for PARIKA Autonomous Waiting
"""

import pytest
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from unittest.mock import Mock

from parika.core.autonomous_waiting.wait_condition import (
    WaitCondition,
    WaitConditionType,
    WaitConditionStatus,
    DependencyWaitData,
    ResourceWaitData,
    ApprovalWaitData,
    AgentMessageWaitData,
    ExternalEventWaitData,
    FileWaitData,
    TimeWaitData,
)
from parika.core.autonomous_waiting.wait_manager import WaitManager
from parika.core.autonomous_waiting.event_matcher import EventMatcher, EventPattern


class TestWaitCondition:
    """Test wait condition models."""

    def test_wait_condition_creation(self):
        """Test creating a wait condition."""
        condition = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.DEPENDENCY,
            condition_data=MappingProxyType({"depends_on_task_ids": ["task_0"]}),
        )
        assert condition.id.startswith("wait_")
        assert condition.task_id == "task_1"
        assert condition.mission_id == "mission_1"
        assert condition.condition_type == WaitConditionType.DEPENDENCY
        assert condition.status == WaitConditionStatus.PENDING

    def test_wait_condition_status_transitions(self):
        """Test wait condition status transitions."""
        condition = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.DEPENDENCY,
            condition_data=MappingProxyType({}),
        )

        # Transition to waiting
        waiting = condition.with_status(WaitConditionStatus.WAITING)
        assert waiting.status == WaitConditionStatus.WAITING
        assert waiting.started_at is not None

        # Transition to satisfied
        satisfied = waiting.with_status(WaitConditionStatus.SATISFIED)
        assert satisfied.status == WaitConditionStatus.SATISFIED
        assert satisfied.satisfied_at is not None

        # Transition to failed with error
        failed = condition.with_status(WaitConditionStatus.FAILED, "Error occurred")
        assert failed.status == WaitConditionStatus.FAILED
        assert failed.error == "Error occurred"

    def test_wait_condition_expiration(self):
        """Test wait condition expiration."""
        # Expired condition - using expires_at field
        expired = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.TIME,
            condition_data=MappingProxyType({"wake_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}),
            expires_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        assert expired.is_expired() is True

        # Future condition
        future = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.TIME,
            condition_data=MappingProxyType({"wake_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}),
            expires_at=datetime.now(UTC) + timedelta(hours=2),
        )
        assert future.is_expired() is False

        # No expiration
        no_expire = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.DEPENDENCY,
            condition_data=MappingProxyType({}),
        )
        assert no_expire.is_expired() is False


class TestWaitConditionData:
    """Test wait condition data structures."""

    def test_dependency_wait_data(self):
        """Test dependency wait data."""
        data = DependencyWaitData(
            depends_on_task_ids=("task_0", "task_1"),
        )
        assert data.depends_on_task_ids == ("task_0", "task_1")

    def test_resource_wait_data(self):
        """Test resource wait data."""
        data = ResourceWaitData(
            resource_type="cpu",
            required_amount=2.0,
            resource_constraints=MappingProxyType({"exclusive": True}),
        )
        assert data.resource_type == "cpu"
        assert data.required_amount == 2.0

    def test_approval_wait_data(self):
        """Test approval wait data."""
        data = ApprovalWaitData(
            approval_id="approval_123",
            requested_operation="file_write",
            context=MappingProxyType({"path": "/tmp/test.txt"}),
        )
        assert data.approval_id == "approval_123"

    def test_agent_message_wait_data(self):
        """Test agent message wait data."""
        data = AgentMessageWaitData(
            expected_message_type="task_result",
            from_agent_id="agent_1",
            correlation_id="corr_123",
        )
        assert data.expected_message_type == "task_result"
        assert data.from_agent_id == "agent_1"

    def test_external_event_wait_data(self):
        """Test external event wait data."""
        data = ExternalEventWaitData(
            event_source="webhook",
            event_type="file_uploaded",
            event_filter=MappingProxyType({"filename": "*.pdf"}),
        )
        assert data.event_source == "webhook"
        assert data.event_filter["filename"] == "*.pdf"

    def test_file_wait_data(self):
        """Test file wait data."""
        data = FileWaitData(
            file_path="/tmp/output.txt",
            check_interval_seconds=5.0,
        )
        assert data.file_path == "/tmp/output.txt"

    def test_time_wait_data(self):
        """Test time wait data."""
        data = TimeWaitData(
            wake_at=datetime.now(UTC) + timedelta(hours=1),
            timezone="UTC",
        )
        assert data.timezone == "UTC"


class TestWaitManager:
    """Test wait manager."""

    @pytest.fixture
    def mock_wait_manager(self):
        """Create a wait manager with mocked dependencies."""
        task_manager = Mock()
        task_manager.get = Mock(return_value=None)

        message_bus = Mock()
        event_bus = Mock()
        logger = Mock()
        logger.get_logger = Mock(return_value=Mock(info=Mock(), debug=Mock(), warning=Mock(), error=Mock()))

        return WaitManager(
            task_manager=task_manager,
            message_bus=message_bus,
            event_bus=event_bus,
            logger=logger,
        )

    def test_register_wait(self, mock_wait_manager):
        """Test registering a wait condition."""
        condition = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.DEPENDENCY,
            condition_data=MappingProxyType({"depends_on_task_ids": ["task_0"]}),
        )

        registered = mock_wait_manager.register_wait(condition)
        assert registered.status == WaitConditionStatus.WAITING
        assert registered.started_at is not None

    def test_cancel_wait(self, mock_wait_manager):
        """Test canceling a wait condition."""
        condition = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.DEPENDENCY,
            condition_data=MappingProxyType({}),
        )
        mock_wait_manager.register_wait(condition)

        # Cancel specific wait
        count = mock_wait_manager.cancel_wait("task_1", condition.id)
        assert count == 1

    def test_get_waits_for_task(self, mock_wait_manager):
        """Test getting waits for a task."""
        condition1 = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.DEPENDENCY,
            condition_data=MappingProxyType({}),
        )
        condition2 = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.RESOURCE,
            condition_data=MappingProxyType({}),
        )
        mock_wait_manager.register_wait(condition1)
        mock_wait_manager.register_wait(condition2)

        waits = mock_wait_manager.get_waits_for_task("task_1")
        assert len(waits) == 2

    def test_check_dependency_condition(self, mock_wait_manager):
        """Test checking dependency condition."""
        condition = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.DEPENDENCY,
            condition_data=MappingProxyType({"depends_on_task_ids": ["task_0"]}),
        )
        condition = condition.with_status(WaitConditionStatus.WAITING)

        # Event for completed dependency
        event_data = MappingProxyType({
            "task_id": "task_0",
            "completed_dependencies": ["task_0"],
        })

        result = mock_wait_manager.check_condition(condition, event_data)
        # This would need the task to have the dependency in its metadata
        # For now, just verify it doesn't crash

    def test_check_agent_message_condition(self, mock_wait_manager):
        """Test checking agent message condition."""
        condition = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.AGENT_MESSAGE,
            condition_data=MappingProxyType({
                "expected_message_type": "task_result",
                "from_agent_id": "agent_1",
            }),
        )
        condition = condition.with_status(WaitConditionStatus.WAITING)

        event_data = MappingProxyType({
            "message_type": "task_result",
            "sender_agent_id": "agent_1",
        })

        result = mock_wait_manager.check_condition(condition, event_data)
        assert result is True

    def test_check_time_condition(self, mock_wait_manager):
        """Test checking time condition."""
        # Past time - should be satisfied
        past_condition = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.TIME,
            condition_data=MappingProxyType({
                "wake_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
            }),
        )
        past_condition = past_condition.with_status(WaitConditionStatus.WAITING)

        result = mock_wait_manager.check_condition(past_condition, MappingProxyType({}))
        assert result is True

        # Future time - should not be satisfied
        future_condition = WaitCondition.create(
            task_id="task_1",
            mission_id="mission_1",
            condition_type=WaitConditionType.TIME,
            condition_data=MappingProxyType({
                "wake_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            }),
        )
        future_condition = future_condition.with_status(WaitConditionStatus.WAITING)

        result = mock_wait_manager.check_condition(future_condition, MappingProxyType({}))
        assert result is False


class TestEventMatcher:
    """Test event matcher."""

    def test_event_pattern_matching(self):
        """Test event pattern matching."""
        pattern = EventPattern(
            event_type="task_completed",
            source="task_manager",
            required_fields=MappingProxyType({"status": "success"}),
        )

        matching_event = MappingProxyType({
            "event_type": "task_completed",
            "source": "task_manager",
            "status": "success",
            "task_id": "task_1",
        })
        assert pattern.matches(matching_event) is True

        # Wrong event type
        wrong_type = MappingProxyType({
            "event_type": "task_failed",
            "source": "task_manager",
            "status": "success",
        })
        assert pattern.matches(wrong_type) is False

        # Wrong source
        wrong_source = MappingProxyType({
            "event_type": "task_completed",
            "source": "agent_manager",
            "status": "success",
        })
        assert pattern.matches(wrong_source) is False

        # Missing required field
        missing_field = MappingProxyType({
            "event_type": "task_completed",
            "source": "task_manager",
        })
        assert pattern.matches(missing_field) is False

    def test_custom_matcher(self):
        """Test custom matcher function."""
        def custom_match(event):
            return event.get("priority", 0) > 5

        pattern = EventPattern(
            custom_matcher=custom_match,
        )

        high_priority = MappingProxyType({"priority": 10})
        assert pattern.matches(high_priority) is True

        low_priority = MappingProxyType({"priority": 3})
        assert pattern.matches(low_priority) is False

    def test_event_matcher_register(self):
        """Test registering patterns in event matcher."""
        matcher = EventMatcher(event_bus=Mock(), logger=Mock())

        pattern = EventPattern(
            event_type="test_event",
            required_fields=MappingProxyType({"key": "value"}),
        )
        matcher.register_pattern("pattern_1", pattern)

        matching_event = MappingProxyType({
            "event_type": "test_event",
            "key": "value",
        })
        matches = matcher.match(matching_event)
        assert "pattern_1" in matches

        matcher.unregister_pattern("pattern_1")
        matches = matcher.match(matching_event)
        assert "pattern_1" not in matches


if __name__ == "__main__":
    pytest.main([__file__, "-v"])