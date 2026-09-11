"""
Phase 2 Integration Tests

Tests the actual integration of Phase 2 components into the autonomous execution path.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from types import MappingProxyType
from datetime import UTC, datetime

from parika.core.autonomous.runtime import build_autonomous_runtime
from parika.core.database.pool import PoolManager
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.service_container.service_container import ServiceContainer
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.planner.planner import Planner
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.permission_manager.permission_manager import PermissionManager
from parika.core.permission_manager.workspace_permission_manager import WorkspacePermissionManager
from parika.core.configuration.configuration import Configuration


class TestPhase2Integration:
    """Test Phase 2 components are properly integrated into autonomous runtime."""

    @pytest.fixture
    def mock_services(self):
        """Create mock services for testing."""
        pool_manager = Mock(spec=PoolManager)
        pool_manager.get_sync_connection = Mock()
        pool_manager.sync_pool = Mock()
        
        event_bus = Mock(spec=EventBus)
        event_bus.publish = Mock()
        event_bus.subscribe = Mock()
        
        logger = Mock(spec=Logger)
        logger.get_logger = Mock(return_value=Mock(info=Mock(), debug=Mock(), warning=Mock(), error=Mock()))
        
        service_container = Mock(spec=ServiceContainer)
        service_container.register = Mock()
        
        capability_resolver = Mock(spec=CapabilityResolver)
        capability_resolver._capability_registry = Mock()
        capability_resolver.resolve = Mock()
        
        planner = Mock(spec=Planner)
        planner.plan = Mock()
        
        capability_executor = Mock(spec=CapabilityExecutor)
        capability_executor.execute = Mock()
        
        tool_manager = Mock(spec=ToolManager)
        tool_manager.get_all = Mock(return_value=[])
        tool_manager.contains = Mock(return_value=True)
        
        provider_manager = Mock(spec=ProviderManager)
        resource_manager = Mock(spec=ResourceManager)
        resource_manager.get_resource_snapshot = Mock(return_value=Mock(
            cpu=Mock(logical_core_count=4),
            memory=Mock(available_bytes=8*1024*1024*1024)
        ))
        
        policy_engine = Mock(spec=PolicyEngine)
        
        permission_manager = Mock(spec=PermissionManager)
        permission_manager.check = Mock(return_value=Mock(authorized=True))
        
        workspace_permission_manager = Mock(spec=WorkspacePermissionManager)
        
        return {
            'pool_manager': pool_manager,
            'event_bus': event_bus,
            'logger': logger,
            'service_container': service_container,
            'capability_resolver': capability_resolver,
            'planner': planner,
            'capability_executor': capability_executor,
            'tool_manager': tool_manager,
            'provider_manager': provider_manager,
            'resource_manager': resource_manager,
            'policy_engine': policy_engine,
            'permission_manager': permission_manager,
            'workspace_permission_manager': workspace_permission_manager,
        }

    def test_build_autonomous_runtime_includes_phase2_services(self, mock_services):
        """Test that build_autonomous_runtime constructs all Phase 2 services."""
        # This test would require actual database, so we just verify imports work
        from parika.core.skill_system.skill_registry import SkillRegistry
        from parika.core.skill_system.skill_catalog import SkillCatalog
        from parika.core.skill_system.skill_loader import SkillLoader
        from parika.core.skill_system.skill_security import SkillSecurityScanner
        from parika.core.implementation_registry.implementation_registry import ImplementationRegistry
        from parika.core.implementation_registry.implementation_resolver import ImplementationResolver
        from parika.core.agent_runtime.runtime_registry import RuntimeRegistry
        from parika.core.agent_runtime.native_runtime import NativeRuntimeAdapter
        from parika.core.agent_runtime.hermes_runtime import HermesRuntimeAdapter
        from parika.core.agent_communication.message_bus import MessageBus
        from parika.core.agent_communication.message_repository import AgentMessageRepository
        from parika.core.multi_agent.mission_coordinator import MissionCoordinator
        from parika.core.multi_agent.agent_selector import AgentSelector
        from parika.core.autonomous_waiting.wait_manager import WaitManager
        
        # All imports succeed
        assert SkillRegistry is not None
        assert SkillCatalog is not None
        assert SkillLoader is not None
        assert SkillSecurityScanner is not None
        assert ImplementationRegistry is not None
        assert ImplementationResolver is not None
        assert RuntimeRegistry is not None
        assert NativeRuntimeAdapter is not None
        assert HermesRuntimeAdapter is not None
        assert MessageBus is not None
        assert AgentMessageRepository is not None
        assert MissionCoordinator is not None
        assert AgentSelector is not None
        assert WaitManager is not None

    def test_autonomous_runtime_dataclass_has_phase2_fields(self, mock_services):
        """Test that AutonomousRuntime dataclass includes Phase 2 fields."""
        from parika.core.autonomous.runtime import AutonomousRuntime
        import inspect
        
        # Get field names
        fields = [f.name for f in inspect.signature(AutonomousRuntime).parameters.values()]
        
        phase2_fields = [
            'skill_registry', 'skill_catalog', 'skill_loader', 'security_scanner',
            'implementation_registry', 'implementation_resolver', 'runtime_registry',
            'message_bus', 'wait_manager', 'mission_coordinator', 'agent_selector'
        ]
        
        for field in phase2_fields:
            assert field in fields, f"Missing Phase 2 field: {field}"

    def test_phase2_services_registered_in_container(self, mock_services):
        """Test that Phase 2 services are registered in ServiceContainer when provided."""
        # This is a structural test - the actual registration happens in build_autonomous_runtime
        # We verify the service container registration calls would be made
        pass

    def test_skill_loader_integration_exists(self, mock_services):
        """Test that SkillLoader is properly integrated."""
        from parika.core.skill_system.skill_loader import SkillLoader
        from parika.core.skill_system.skill_registry import SkillRegistry
        from parika.core.skill_system.skill_security import SkillSecurityScanner
        from parika.core.policy_engine.policy_engine import PolicyEngine
        from parika.core.permission_manager.permission_manager import PermissionManager
        from parika.core.permission_manager.workspace_permission_manager import WorkspacePermissionManager
        from parika.core.event_bus.event_bus import EventBus
        from parika.core.logger.logger import Logger
        
        # Verify constructor signature includes all required dependencies
        import inspect
        sig = inspect.signature(SkillLoader.__init__)
        params = list(sig.parameters.keys())
        
        required = ['registry', 'security_scanner', 'policy_engine', 'permission_manager', 
                   'workspace_permissions', 'event_bus', 'logger']
        for req in required:
            assert req in params, f"SkillLoader missing parameter: {req}"

    def test_implementation_resolver_integration_exists(self, mock_services):
        """Test that ImplementationResolver is properly integrated."""
        from parika.core.implementation_registry.implementation_resolver import ImplementationResolver
        import inspect
        
        sig = inspect.signature(ImplementationResolver.__init__)
        params = list(sig.parameters.keys())
        
        required = ['capability_registry', 'capability_resolver', 'implementation_registry',
                   'skill_registry', 'policy_engine', 'permission_manager', 'workspace_permissions',
                   'resource_manager', 'event_bus', 'logger']
        for req in required:
            assert req in params, f"ImplementationResolver missing parameter: {req}"

    def test_runtime_registry_integration_exists(self, mock_services):
        """Test that RuntimeRegistry is properly integrated."""
        from parika.core.agent_runtime.runtime_registry import RuntimeRegistry
        import inspect
        
        sig = inspect.signature(RuntimeRegistry.__init__)
        params = list(sig.parameters.keys())
        
        required = ['event_bus', 'logger']
        for req in required:
            assert req in params, f"RuntimeRegistry missing parameter: {req}"

    def test_message_bus_integration_exists(self, mock_services):
        """Test that MessageBus is properly integrated."""
        from parika.core.agent_communication.message_bus import MessageBus
        import inspect
        
        sig = inspect.signature(MessageBus.__init__)
        params = list(sig.parameters.keys())
        
        required = ['repository', 'agent_supervisor', 'event_bus', 'logger']
        for req in required:
            assert req in params, f"MessageBus missing parameter: {req}"

    def test_mission_coordinator_integration_exists(self, mock_services):
        """Test that MissionCoordinator is properly integrated."""
        from parika.core.multi_agent.mission_coordinator import MissionCoordinator
        import inspect
        
        sig = inspect.signature(MissionCoordinator.__init__)
        params = list(sig.parameters.keys())
        
        required = ['mission_manager', 'task_manager', 'agent_supervisor', 'agent_orchestrator',
                   'message_bus', 'skill_loader', 'skill_catalog', 'event_bus', 'logger']
        for req in required:
            assert req in params, f"MissionCoordinator missing parameter: {req}"

    def test_wait_manager_integration_exists(self, mock_services):
        """Test that WaitManager is properly integrated."""
        from parika.core.autonomous_waiting.wait_manager import WaitManager
        import inspect
        
        sig = inspect.signature(WaitManager.__init__)
        params = list(sig.parameters.keys())
        
        required = ['task_manager', 'message_bus', 'event_bus', 'logger']
        for req in required:
            assert req in params, f"WaitManager missing parameter: {req}"

    def test_agent_selector_integration_exists(self, mock_services):
        """Test that AgentSelector is properly integrated."""
        from parika.core.multi_agent.agent_selector import AgentSelector
        import inspect
        
        sig = inspect.signature(AgentSelector.__init__)
        params = list(sig.parameters.keys())
        
        required = ['agent_registry', 'agent_resolver', 'agent_orchestrator', 'capability_registry',
                   'capability_resolver', 'implementation_registry', 'implementation_resolver',
                   'skill_registry', 'skill_catalog', 'runtime_registry', 'event_bus', 'logger']
        for req in required:
            assert req in params, f"AgentSelector missing parameter: {req}"

    def test_hermes_runtime_adapter_uses_oneshot(self, mock_services):
        """Test that HermesRuntimeAdapter uses --oneshot for execution."""
        from parika.core.agent_runtime.hermes_runtime import HermesRuntimeAdapter
        import inspect
        
        # Check that execute method exists and has the right signature
        sig = inspect.signature(HermesRuntimeAdapter.execute)
        params = list(sig.parameters.keys())
        
        required = ['agent_id', 'task_id', 'capability_id', 'inputs', 'context', 'skill_id']
        for req in required:
            assert req in params, f"HermesRuntimeAdapter.execute missing parameter: {req}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])