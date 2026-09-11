"""
Tests for Authorization and Budget enforcement.
"""

from types import MappingProxyType
from unittest.mock import Mock

import pytest

from parika.core.autonomous import (
    AutonomousAuthorizationBoundary,
    BudgetEnforcer,
    AutonomousAuthorizationRequest,
)
from parika.core.policy_engine.policy_effect import PolicyEffect
from parika.core.policy_engine.request import PolicyEvaluationRequest
from parika.core.policy_engine.policy_context import PolicyContext


class TestAutonomousAuthorizationBoundary:
    """Tests for AutonomousAuthorizationBoundary."""

    def _make_boundary(self):
        """Create a boundary with mocked dependencies."""
        mock_policy_engine = Mock()
        mock_permission_manager = Mock()
        mock_workspace_permission_manager = Mock()
        mock_logger = Mock()
        mock_logger.get_logger = Mock(return_value=Mock())

        # Default policy evaluation allows
        mock_decision = Mock()
        mock_decision.effect = PolicyEffect.ALLOW
        mock_decision.reason = "Allowed"
        mock_decision.matched_rule_id = "test-rule"
        mock_policy_engine.evaluate = Mock(return_value=mock_decision)

        # Default permission manager allows
        mock_permission_manager.check = Mock(return_value=True)

        # Default workspace permission manager allows
        mock_workspace_permission_manager.check = Mock(return_value=True)

        return AutonomousAuthorizationBoundary(
            policy_engine=mock_policy_engine,
            permission_manager=mock_permission_manager,
            workspace_permission_manager=mock_workspace_permission_manager,
            logger=Mock(),
        )

    def test_allows_when_policy_allows(self):
        """Test authorization allows when policy allows."""
        boundary = self._make_boundary()

        request = AutonomousAuthorizationRequest(
            agent_id="agent-1",
            agent_profile_id="profile-1",
            capability_id="vision.provider_describe_image",
            inputs=MappingProxyType({"images_base64": ["img"]}),
            mission_id="mission-1",
            task_id="task-1",
            permission_context=MappingProxyType({}),
            resource_budget=MappingProxyType({}),
        )

        decision = boundary.authorize(request)

        assert decision.allowed is True
        assert decision.reason is None

    def test_denies_when_policy_denies(self):
        """Test authorization denies when policy denies."""
        boundary = self._make_boundary()

        # Override to deny
        from parika.core.policy_engine.policy_effect import PolicyEffect
        mock_decision = Mock()
        mock_decision.effect = PolicyEffect.DENY
        mock_decision.reason = "Policy denied"
        mock_decision.matched_rule_id = "deny-rule"
        boundary._policy_engine.evaluate = Mock(return_value=mock_decision)

        request = AutonomousAuthorizationRequest(
            agent_id="agent-1",
            agent_profile_id="profile-1",
            capability_id="filesystem.delete",
            inputs=MappingProxyType({}),
            mission_id="mission-1",
            task_id="task-1",
            permission_context=MappingProxyType({}),
            resource_budget=MappingProxyType({}),
        )

        decision = boundary.authorize(request)

        assert decision.allowed is False
        assert "Policy denied" in decision.reason

    def test_filesystem_requires_workspace_path(self):
        """Test filesystem capabilities require workspace path."""
        boundary = self._make_boundary()

        request = AutonomousAuthorizationRequest(
            agent_id="agent-1",
            agent_profile_id="profile-1",
            capability_id="filesystem.delete",
            inputs=MappingProxyType({"path": "/tmp/test"}),
            mission_id="mission-1",
            task_id="task-1",
            permission_context=MappingProxyType({}),  # No workspace_path
            resource_budget=MappingProxyType({}),
        )

        decision = boundary.authorize(request)

        assert decision.allowed is False
        assert "workspace path" in decision.reason.lower()

    def test_filesystem_allows_trusted_workspace(self):
        """Test filesystem allows when workspace is trusted."""
        boundary = self._make_boundary()

        request = AutonomousAuthorizationRequest(
            agent_id="agent-1",
            agent_profile_id="profile-1",
            capability_id="filesystem.delete",
            inputs=MappingProxyType({"path": "/tmp/test"}),
            mission_id="mission-1",
            task_id="task-1",
            permission_context=MappingProxyType({
                "workspace_path": "/tmp/test",
                "trusted_workspaces": ["/tmp/test"],
            }),
            resource_budget=MappingProxyType({}),
        )

        decision = boundary.authorize(request)

        assert decision.allowed is True


class TestBudgetEnforcer:
    """Tests for BudgetEnforcer."""

    def _make_enforcer(self):
        """Create a budget enforcer with mocked resource manager."""
        mock_resource_manager = Mock()
        mock_resource_manager.get_resource_snapshot = Mock(return_value=Mock(
            cpu=Mock(usage_percent=50.0),
            memory=Mock(usage_percent=60.0),
        ))
        mock_logger = Mock()
        mock_logger.get_logger = Mock(return_value=Mock())

        return BudgetEnforcer(
            resource_manager=mock_resource_manager,
            logger=Mock(),
        )

    def test_set_budget(self):
        """Test setting budget for a task."""
        enforcer = self._make_enforcer()

        budget = MappingProxyType({
            "max_runtime_seconds": 300,
            "max_retries": 3,
            "max_children": 5,
        })

        limit = enforcer.set_budget("task-1", budget)

        assert limit.max_runtime_seconds == 300
        assert limit.max_retries == 3
        assert limit.max_children == 5

    def test_check_budget_allows_within_limits(self):
        """Test budget check allows when within limits."""
        enforcer = self._make_enforcer()

        enforcer.set_budget("task-1", MappingProxyType({
            "max_runtime_seconds": 300,
            "max_retries": 3,
        }))

        # Fast-forward time to simulate some runtime
        result = enforcer.check_budget("task-1")

        assert result.allowed is True
        assert len(result.violations) == 0

    def test_check_budget_denies_runtime_exceeded(self):
        """Test budget check denies when runtime exceeded."""
        enforcer = self._make_enforcer()

        enforcer.set_budget("task-1", MappingProxyType({
            "max_runtime_seconds": 1,  # 1 second limit
        }))

        # Manually set start time to past
        from datetime import UTC, datetime, timedelta
        enforcer._task_start_times["task-1"] = datetime.now(UTC) - timedelta(seconds=2)

        result = enforcer.check_budget("task-1")

        assert result.allowed is False
        assert len(result.violations) == 1
        assert "max_runtime_seconds" in result.violations[0].limit_name

    def test_check_budget_denies_retries_exceeded(self):
        """Test budget check denies when retries exceeded."""
        enforcer = self._make_enforcer()

        enforcer.set_budget("task-1", MappingProxyType({
            "max_retries": 2,
        }))

        # Record 3 retries
        enforcer.record_retry("task-1")
        enforcer.record_retry("task-1")
        enforcer.record_retry("task-1")

        result = enforcer.check_budget("task-1")

        assert result.allowed is False
        assert any("max_retries" in v.limit_name for v in result.violations)

    def test_record_retry_increments(self):
        """Test recording retry increments count."""
        enforcer = self._make_enforcer()

        enforcer.set_budget("task-1", MappingProxyType({"max_retries": 3}))

        enforcer.record_retry("task-1")
        enforcer.record_retry("task-1")

        usage = enforcer.get_usage("task-1")
        assert usage is not None
        assert usage.retries == 2

    def test_record_worker_start_end(self):
        """Test recording worker start/end for concurrency tracking."""
        enforcer = self._make_enforcer()

        enforcer.set_budget("task-1", MappingProxyType({
            "max_concurrent_workers": 2,
        }))

        enforcer.record_worker_start("task-1")
        enforcer.record_worker_start("task-1")

        usage = enforcer.get_usage("task-1")
        assert usage.concurrent_workers == 2

        enforcer.record_worker_end("task-1")
        usage = enforcer.get_usage("task-1")
        assert usage.concurrent_workers == 1

    def test_cleanup_removes_budget(self):
        """Test cleanup removes budget tracking."""
        enforcer = self._make_enforcer()

        enforcer.set_budget("task-1", MappingProxyType({"max_retries": 3}))
        enforcer.cleanup("task-1")

        assert enforcer.get_limit("task-1") is None
        assert enforcer.get_usage("task-1") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])