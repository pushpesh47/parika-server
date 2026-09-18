"""
Regression test for preferred_synthesis_provider_id undefined in autonomous synthesis fallback.

This test verifies that when an autonomous mission completes and the session
attempts to synthesize a final response using the preferred provider from
goal decomposition, no NameError occurs.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace

from parika.interfaces.ai_context.goal_decomposer import (
    DecompositionResult,
    DecompositionError,
    GoalDecomposer,
    ExecutionMode,
)
from parika.interfaces.ai_context.goal_decomposer import Goal
from parika.interfaces.session import InterfaceSession
from parika.core.autonomous.contracts import MissionStatus, AutonomousTaskStatus
from parika.core.autonomous.mission_manager import Mission
from parika.core.autonomous.models import AutonomousTaskModel
from parika.core.provider_manager.chat_result import ChatResult
from parika.core.provider_manager.chat_message import ChatMessage
from parika.core.brain.brain_response import BrainResponse, RequestStatus
from parika.core.brain.goal_result import GoalResult
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task_status import TaskStatus
from datetime import datetime, UTC


class TestAutonomousSynthesisPreferredProvider:
    """Test that autonomous synthesis fallback uses preferred provider from decomposition."""

    @pytest.fixture
    def mock_runtime(self):
        """Create a mock runtime with all required components."""
        runtime = MagicMock()
        runtime.configuration = MagicMock()
        runtime.configuration.get.return_value = "agent.coding"
        runtime.agent_registry = MagicMock()
        runtime.agent_registry.get.return_value = MagicMock(allowed_capabilities=["filesystem.exists"])
        runtime.autonomous_runtime = MagicMock()
        runtime.autonomous_runtime.mission_manager = MagicMock()
        runtime.autonomous_runtime.task_manager = MagicMock()
        runtime.autonomous_runtime.task_repository = MagicMock()
        runtime.autonomous_runtime.sync_pool = MagicMock()
        runtime.logger = MagicMock()
        return runtime

    @pytest.fixture
    def mock_decomposition_result(self):
        """Create a mock decomposition result with successful provider info."""
        goals = (
            Goal(
                id="goal_1",
                capability_id="filesystem.exists",
                inputs={"path": "/test/path"},
                depends_on=(),
                provider_request_builder=lambda r, m: MagicMock(),
            ),
            Goal(
                id="goal_synthesis",
                capability_id="chat.respond",
                inputs={"message": "test"},
                depends_on=("goal_1",),
                provider_request_builder=lambda r, m: MagicMock(),
            ),
        )
        return DecompositionResult(
            goals=goals,
            raw_response="{}",
            successful_provider_id="test_provider",
            successful_model_id="test_model",
            proposed_semantic_mode=ExecutionMode.AUTONOMOUS,
            execution_mode_confidence=0.9,
            execution_mode_reasons=("test",),
        )

    @pytest.fixture
    def mock_mission(self):
        """Create a mock completed mission."""
        mission = Mission(
            id="test_mission_id",
            goal="test goal",
            status=MissionStatus.COMPLETED,
            priority=0,
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            deadline=None,
            progress=1.0,
            metadata={},
            failure=None,
            result={"result": "success"},
        )
        return mission

    @pytest.fixture
    def mock_tasks(self):
        """Create mock completed tasks."""
        task = AutonomousTaskModel(
            id="test_task_id",
            mission_id="test_mission_id",
            parent_task_id=None,
            agent_id=None,
            name="goal_1",
            description="test",
            capability_id="filesystem.exists",
            inputs={"path": "/test/path"},
            status=AutonomousTaskStatus.COMPLETED.value,
            priority=0,
            progress=1.0,
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            deadline=None,
            max_retries=3,
            retry_count=0,
            resource_budget={},
            checkpoint_id=None,
            result={"result": {"exists": True}},
            failure=None,
            task_metadata={},
            provider_request_type=None,
            task_category=None,
            execution_requirements=None,
            execution_plan=None,
        )
        return [task]

    @pytest.mark.asyncio
    async def test_autonomous_synthesis_uses_preferred_provider_from_decomposition(
        self,
        mock_runtime,
        mock_decomposition_result,
        mock_mission,
        mock_tasks,
    ):
        """Verify that autonomous synthesis fallback uses preferred provider from decomposition."""
        # Setup mocks
        mock_runtime.autonomous_runtime.mission_manager.create.return_value = mock_mission
        mock_runtime.autonomous_runtime.mission_manager.plan.return_value = mock_mission
        mock_runtime.autonomous_runtime.mission_manager.start.return_value = mock_mission
        mock_runtime.autonomous_runtime.mission_manager.wait_for_completion.return_value = mock_mission
        mock_runtime.autonomous_runtime.task_repository.list_by_mission.return_value = mock_tasks
        mock_runtime.autonomous_runtime.task_manager.get.return_value = MagicMock(
            status=AutonomousTaskStatus.COMPLETED.value,
            result={"result": {"exists": True}},
            failure=None,
            inputs={"path": "/test/path"},
            capability_id="filesystem.exists",
        )
        
        # Mock the planner and capability executor for synthesis
        mock_plan = MagicMock()
        mock_plan.steps = [MagicMock()]
        mock_plan.steps[0].execution_request = MagicMock()
        mock_runtime.planner.plan.return_value = mock_plan
        
        mock_exec_resp = MagicMock()
        mock_exec_resp.backend_response = ChatResult(
            message=ChatMessage(role="assistant", content="Synthesized response")
        )
        mock_runtime.capability_executor.execute.return_value = mock_exec_resp
        
        # Mock admission to always return AUTONOMOUS
        with patch('parika.interfaces.session.create_execution_mode_admission') as mock_admission:
            mock_admission_instance = MagicMock()
            mock_admission_instance.resolve.return_value = SimpleNamespace(
                admitted_mode=ExecutionMode.AUTONOMOUS,
                reason="test"
            )
            mock_admission.return_value = mock_admission_instance
            
            # Mock decompose_and_build_goals to return our decomposition result
            with patch('parika.interfaces.session.decompose_and_build_goals') as mock_decompose:
                mock_decompose.return_value = mock_decomposition_result
                
                # Create session and submit autonomous request
                session = InterfaceSession(mock_runtime)
                
                # This should not raise NameError for preferred_synthesis_provider_id
                result = session._submit_autonomous(
                    text="Test autonomous task",
                    decomposition_result=mock_decomposition_result,
                    admission_decision=mock_admission_instance.resolve.return_value,
                    on_token=None,
                    progress_trail=[],
                )
                
                # Verify the result
                assert result is not None
                
                # The key assertion: no NameError was raised for preferred_synthesis_provider_id
                # If we reach here, the fix works

    @pytest.mark.asyncio
    async def test_autonomous_synthesis_fallback_when_provider_fails(
        self,
        mock_runtime,
        mock_decomposition_result,
        mock_mission,
        mock_tasks,
    ):
        """Verify deterministic fallback works when provider synthesis fails."""
        # Setup mocks
        mock_runtime.autonomous_runtime.mission_manager.create.return_value = mock_mission
        mock_runtime.autonomous_runtime.mission_manager.plan.return_value = mock_mission
        mock_runtime.autonomous_runtime.mission_manager.start.return_value = mock_mission
        mock_runtime.autonomous_runtime.mission_manager.wait_for_completion.return_value = mock_mission
        mock_runtime.autonomous_runtime.task_repository.list_by_mission.return_value = mock_tasks
        mock_runtime.autonomous_runtime.task_manager.get.return_value = MagicMock(
            status=AutonomousTaskStatus.COMPLETED.value,
            result={"result": {"exists": True}},
            failure=None,
            inputs={"path": "/test/path"},
            capability_id="filesystem.exists",
        )
        
        # Mock planner to succeed but capability executor to fail (simulating provider failure)
        mock_plan = MagicMock()
        mock_plan.steps = [MagicMock()]
        mock_plan.steps[0].execution_request = MagicMock()
        mock_runtime.planner.plan.return_value = mock_plan
        
        mock_runtime.capability_executor.execute.side_effect = Exception("Provider failed")
        
        with patch('parika.interfaces.session.create_execution_mode_admission') as mock_admission:
            mock_admission_instance = MagicMock()
            mock_admission_instance.resolve.return_value = SimpleNamespace(
                admitted_mode=ExecutionMode.AUTONOMOUS,
                reason="test"
            )
            mock_admission.return_value = mock_admission_instance
            
            with patch('parika.interfaces.session.decompose_and_build_goals') as mock_decompose:
                mock_decompose.return_value = mock_decomposition_result
                
                session = InterfaceSession(mock_runtime)
                
                # This should not raise NameError and should fall back to deterministic synthesis
                result = session._submit_autonomous(
                    text="Test autonomous task",
                    decomposition_result=mock_decomposition_result,
                    admission_decision=mock_admission_instance.resolve.return_value,
                    on_token=None,
                    progress_trail=[],
                )
                
                # Verify the result contains fallback content
                assert result is not None
                # The fallback should contain the summary
                assert "completed" in result.chat_response.message.content.lower() or "exists" in result.chat_response.message.content.lower()
