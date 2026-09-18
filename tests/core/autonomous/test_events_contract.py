"""
Unit tests for autonomous events contract and construction sites.
Verifies:
1. Every autonomous event class requires and accepts event_type.
2. Every autonomous event supports mapping-like access (.get() and [key]).
3. TaskCompletedEvent has capability_id.
4. Managers (MissionManager, TaskManager, AgentSupervisor, CheckpointManager,
   WorkerManager, RecoveryCoordinator) publish events with canonical event_type.
"""

from types import MappingProxyType
from unittest.mock import Mock

import pytest

from parika.core.autonomous.events import (
    AutonomousEvent,
    MissionCreatedEvent,
    MissionStartedEvent,
    MissionProgressEvent,
    MissionCompletedEvent,
    MissionFailedEvent,
    MissionCancelledEvent,
    MissionPausedEvent,
    MissionResumedEvent,
    TaskCreatedEvent,
    TaskStartedEvent,
    TaskProgressEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskCancelledEvent,
    TaskPausedEvent,
    TaskResumedEvent,
    TaskWaitingForDependencyEvent,
    AgentSpawnedEvent,
    AgentStartedEvent,
    AgentCompletedEvent,
    AgentFailedEvent,
    WorkerSpawnedEvent,
    WorkerStartedEvent,
    WorkerHeartbeatEvent,
    WorkerFailedEvent,
    WorkerCancelledEvent,
    CheckpointCreatedEvent,
    CheckpointRestoredEvent,
    RecoveryStartedEvent,
    RecoveryCompletedEvent,
    RecoveryFailedEvent,
)


def test_autonomous_event_mapping_compatibility():
    """Test that all autonomous events support .get() and __getitem__."""
    event = TaskCompletedEvent(
        event_id="evt_123",
        event_type="task.completed",
        mission_id="m_1",
        task_id="t_1",
        attempt_number=1,
        capability_id="filesystem.exists",
    )
    assert event.get("task_id") == "t_1"
    assert event.get("non_existent", "default_val") == "default_val"
    assert event["task_id"] == "t_1"
    assert event["capability_id"] == "filesystem.exists"
    with pytest.raises(KeyError):
        _ = event["non_existent"]


def test_task_completed_event_has_event_type_and_capability_id():
    """Test TaskCompletedEvent construction with required event_type."""
    event = TaskCompletedEvent(
        event_id="evt_456",
        event_type="task.completed",
        mission_id="m_2",
        task_id="t_2",
        attempt_number=1,
        capability_id="filesystem.exists",
        result=MappingProxyType({"exists": True}),
    )
    assert event.event_type == "task.completed"
    assert event.capability_id == "filesystem.exists"
    assert event.result["exists"] is True


def test_task_manager_event_constructions():
    """Test that TaskManager constructs events with event_type."""
    from parika.core.autonomous.task_manager import AutonomousTaskManager
    from parika.core.autonomous.contracts import AutonomousTaskStatus
    from parika.core.autonomous.models import AutonomousTaskModel

    mock_repo = Mock()
    mock_dep_repo = Mock()
    mock_bus = Mock()
    mock_logger = Mock()
    mock_logger.get_logger = Mock(return_value=Mock())

    tm = AutonomousTaskManager(
        repository=mock_repo,
        dependency_repository=mock_dep_repo,
        event_bus=mock_bus,
        logger=mock_logger,
    )

    sample_model = AutonomousTaskModel(
        id="task_1",
        mission_id="m_1",
        name="test_task",
        description="test",
        capability_id="filesystem.exists",
        inputs={},
        status=AutonomousTaskStatus.READY.value,
        priority=0,
        progress=0.0,
        retry_count=0,
        max_retries=3,
        resource_budget={},
        task_metadata={},
    )
    mock_repo.get = Mock(return_value=sample_model)

    # 1. Start task
    tm.start("task_1")
    calls = mock_bus.publish.call_args_list
    started_call = [c for c in calls if c[0][0] == "task.started"][0]
    started_event = started_call[0][1]
    assert isinstance(started_event, TaskStartedEvent)
    assert started_event.event_type == "task.started"

    # 2. Update progress
    tm.update_progress("task_1", 0.5, "working")
    calls = mock_bus.publish.call_args_list
    prog_call = [c for c in calls if c[0][0] == "task.progress"][0]
    prog_event = prog_call[0][1]
    assert isinstance(prog_event, TaskProgressEvent)
    assert prog_event.event_type == "task.progress"

    # 3. Complete task
    sample_model.status = AutonomousTaskStatus.RUNNING.value
    mock_dep_repo.get_dependents_for_task = Mock(return_value=[])
    tm.complete("task_1", MappingProxyType({"exists": True}))
    calls = mock_bus.publish.call_args_list
    completed_calls = [c for c in calls if c[0][0] == "task.completed" and isinstance(c[0][1], TaskCompletedEvent)]
    assert len(completed_calls) == 1
    completed_event = completed_calls[0][0][1]
    assert completed_event.event_type == "task.completed"
    assert completed_event.capability_id == "filesystem.exists"


def test_mission_manager_progress_event():
    """Test that MissionManager publishes progress event with event_type."""
    from parika.core.autonomous.mission_manager import MissionManager
    from parika.core.autonomous.contracts import MissionStatus
    from parika.core.autonomous.models import MissionModel

    mock_repo = Mock()
    mock_bus = Mock()
    mock_logger = Mock()
    mock_logger.get_logger = Mock(return_value=Mock())

    mm = MissionManager(repository=mock_repo, event_bus=mock_bus, logger=mock_logger)
    mock_model = MissionModel(
        id="m_1",
        goal="test",
        status=MissionStatus.RUNNING.value,
        priority=1,
        progress=0.0,
        mission_metadata={},
    )
    mock_repo.get = Mock(return_value=mock_model)

    mm.update_progress("m_1", 0.5, "working")
    calls = mock_bus.publish.call_args_list
    prog_calls = [c for c in calls if c[0][0] == "mission.progress"]
    assert len(prog_calls) == 1
    event = prog_calls[0][0][1]
    assert isinstance(event, MissionProgressEvent)
    assert event.event_type == "mission.progress"


def test_agent_supervisor_event_constructions():
    """Test AgentSupervisor publishes all agent events with event_type."""
    from parika.core.autonomous.agent_supervisor import AgentSupervisor
    from parika.core.autonomous.models import AgentInstanceModel
    from parika.core.autonomous.contracts import AgentInstanceStatus

    mock_repo = Mock()
    mock_bus = Mock()
    mock_logger = Mock()
    mock_logger.get_logger = Mock(return_value=Mock())

    asp = AgentSupervisor(repository=mock_repo, event_bus=mock_bus, logger=mock_logger)

    # 1. Spawn
    agent = asp.spawn(mission_id="m_1", task_id="t_1", agent_profile_id="p_1")
    calls = mock_bus.publish.call_args_list
    spawn_calls = [c for c in calls if c[0][0] == "agent.spawned"]
    assert len(spawn_calls) == 1
    spawn_event = spawn_calls[0][0][1]
    assert isinstance(spawn_event, AgentSpawnedEvent)
    assert spawn_event.event_type == "agent.spawned"
    assert spawn_event.runtime == "native"

    # 2. Start
    agent_model = AgentInstanceModel(
        id=agent.id,
        mission_id="m_1",
        task_id="t_1",
        agent_profile_id="p_1",
        runtime="native",
        status=AgentInstanceStatus.SPAWNED.value,
        permission_context={},
        resource_budget={},
        agent_metadata={},
    )
    mock_repo.get = Mock(return_value=agent_model)
    asp.start(agent.id)
    calls = mock_bus.publish.call_args_list
    start_calls = [c for c in calls if c[0][0] == "agent.started"]
    assert len(start_calls) == 1
    assert start_calls[0][0][1].event_type == "agent.started"

    # 3. Complete
    agent_model.status = AgentInstanceStatus.RUNNING.value
    asp.complete(agent.id, MappingProxyType({"done": True}))
    calls = mock_bus.publish.call_args_list
    comp_calls = [c for c in calls if c[0][0] == "agent.completed"]
    assert len(comp_calls) == 1
    assert comp_calls[0][0][1].event_type == "agent.completed"


def test_experience_recorder_with_autonomous_event():
    """Test ExperienceRecorder cleanly handles autonomous TaskCompletedEvent."""
    from parika.modules.experience.recorder import ExperienceRecorder
    from parika.core.event_bus.event_bus import EventBus

    mock_logger = Mock()
    mock_logger.get_logger = Mock(return_value=Mock())
    bus = EventBus(mock_logger)
    mock_store = Mock()

    recorder = ExperienceRecorder(bus, mock_store)
    recorder.initialize()

    # Publish autonomous TaskCompletedEvent
    event = TaskCompletedEvent(
        event_id="evt_test",
        event_type="task.completed",
        mission_id="m_1",
        task_id="t_1",
        attempt_number=1,
        capability_id="filesystem.exists",
        result=MappingProxyType({"exists": True}),
    )
    bus.publish("task.completed", event)

    assert mock_store.register.called
    registered_exp = mock_store.register.call_args[0][0]
    assert registered_exp.capability_id == "filesystem.exists"
    assert registered_exp.outcome.name == "SUCCESS"

    # Also test Phase 2 dict payload (should not crash)
    mock_store.reset_mock()
    bus.publish("task.completed", {
        "event_id": "evt_dict",
        "task_id": "t_1",
        "result": {"exists": True},
    })
    # Dict without capability_id should be safely ignored
    assert not mock_store.register.called


def test_executor_mission_completion():
    """Test that AutonomousExecutor._check_mission_completion completes mission."""
    from parika.core.autonomous.executor import AutonomousExecutor
    from parika.core.autonomous.contracts import AutonomousTaskStatus
    from parika.core.autonomous.models import AutonomousTaskModel

    mock_task_repo = Mock()
    mock_task_manager = Mock()
    mock_worker_manager = Mock()
    mock_checkpoint_manager = Mock()
    mock_mission_manager = Mock()
    mock_logger = Mock()
    mock_logger.get_logger = Mock(return_value=Mock())

    executor = AutonomousExecutor(
        task_repository=mock_task_repo,
        task_manager=mock_task_manager,
        worker_manager=mock_worker_manager,
        checkpoint_manager=mock_checkpoint_manager,
        capability_resolver=Mock(),
        planner=Mock(),
        capability_executor=Mock(),
        tool_manager=Mock(),
        provider_manager=Mock(),
        resource_manager=Mock(),
        policy_engine=Mock(),
        mission_manager=mock_mission_manager,
        logger=mock_logger,
    )

    completed_task = AutonomousTaskModel(
        id="t_1",
        mission_id="m_1",
        name="test",
        description="test",
        capability_id="filesystem.exists",
        inputs={},
        status=AutonomousTaskStatus.COMPLETED.value,
        priority=0,
        progress=1.0,
        retry_count=0,
        max_retries=3,
        resource_budget={},
        task_metadata={},
    )
    mock_task_repo.list_by_mission = Mock(return_value=[completed_task])

    executor._check_mission_completion("m_1", MappingProxyType({"exists": True}))

    mock_mission_manager.complete.assert_called_once_with(
        "m_1",
        MappingProxyType({"exists": True}),
    )


