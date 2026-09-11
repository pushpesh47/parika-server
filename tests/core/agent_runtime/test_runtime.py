"""
Tests for PARIKA Agent Runtime
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from types import MappingProxyType

from parika.core.agent_runtime.contracts import (
    AgentRuntime,
    RuntimeType,
    RuntimeStatus,
    RuntimeCapabilities,
    RuntimeConfig,
    RuntimeExecutionRequest,
    RuntimeExecutionResult,
)


class TestRuntimeContracts:
    """Test runtime contracts."""

    def test_runtime_type_enum(self):
        """Test runtime type enum."""
        assert RuntimeType.NATIVE.value == "native"
        assert RuntimeType.HERMES.value == "hermes"
        assert RuntimeType.REMOTE.value == "remote"

    def test_runtime_status_enum(self):
        """Test runtime status enum."""
        assert RuntimeStatus.STOPPED.value == "stopped"
        assert RuntimeStatus.STARTING.value == "starting"
        assert RuntimeStatus.RUNNING.value == "running"
        assert RuntimeStatus.PAUSED.value == "paused"
        assert RuntimeStatus.ERROR.value == "error"

    def test_runtime_capabilities(self):
        """Test runtime capabilities."""
        caps = RuntimeCapabilities(
            supported_capability_categories=("tool", "llm"),
            max_concurrent_agents=10,
            supports_checkpoint=True,
            supports_skills=True,
            supports_tools=True,
            supports_a2a=False,
            supports_streaming=True,
            resource_isolation="process",
        )
        assert caps.max_concurrent_agents == 10
        assert caps.supports_checkpoint is True
        assert caps.resource_isolation == "process"

    def test_runtime_config(self):
        """Test runtime config."""
        config = RuntimeConfig(
            runtime_type=RuntimeType.NATIVE,
            runtime_id="native_1",
            name="Native Runtime",
            config=MappingProxyType({"key": "value"}),
            resource_limits=MappingProxyType({"cpu": 2}),
            environment=MappingProxyType({"ENV": "value"}),
            enabled=True,
        )
        assert config.runtime_type == RuntimeType.NATIVE
        assert config.runtime_id == "native_1"
        assert config.name == "Native Runtime"

    def test_runtime_execution_request(self):
        """Test runtime execution request."""
        request = RuntimeExecutionRequest(
            agent_id="agent_1",
            task_id="task_1",
            capability_id="filesystem.read",
            inputs=MappingProxyType({"path": "/tmp/test.txt"}),
            context=MappingProxyType({"mission_id": "mission_1"}),
            skill_id="skill_1",
            implementation_id="impl_1",
            timeout_seconds=60.0,
        )
        assert request.agent_id == "agent_1"
        assert request.capability_id == "filesystem.read"
        assert request.skill_id == "skill_1"

    def test_runtime_execution_result(self):
        """Test runtime execution result."""
        result = RuntimeExecutionResult(
            success=True,
            result=MappingProxyType({"content": "file content"}),
            execution_time_ms=150.0,
            checkpoint=MappingProxyType({"state": "saved"}),
            metadata=MappingProxyType({"runtime": "native"}),
        )
        assert result.success is True
        assert result.result["content"] == "file content"
        assert result.execution_time_ms == 150.0


class TestNativeRuntimeAdapter:
    """Test native runtime adapter."""

    @pytest.mark.asyncio
    async def test_native_runtime_lifecycle(self):
        """Test native runtime lifecycle."""
        # This would need full mocking of dependencies
        # For now, just verify the class can be imported
        from parika.core.agent_runtime.native_runtime import NativeRuntimeAdapter
        assert NativeRuntimeAdapter is not None


class TestHermesRuntimeAdapter:
    """Test Hermes runtime adapter."""

    @pytest.mark.asyncio
    async def test_hermes_runtime_validation(self):
        """Test Hermes runtime validation."""
        from parika.core.agent_runtime.hermes_runtime import HermesRuntimeAdapter
        assert HermesRuntimeAdapter is not None


class TestRuntimeRegistry:
    """Test runtime registry."""

    @pytest.fixture
    def mock_registry(self):
        """Create a registry with mocked dependencies."""
        event_bus = Mock()
        logger = Mock()
        logger.get_logger = Mock(return_value=Mock(info=Mock(), debug=Mock(), warning=Mock(), error=Mock()))

        from parika.core.agent_runtime.runtime_registry import RuntimeRegistry
        return RuntimeRegistry(event_bus=event_bus, logger=logger)

    @pytest.mark.asyncio
    async def test_register_runtime(self, mock_registry):
        """Test registering a runtime."""
        config = RuntimeConfig(
            runtime_type=RuntimeType.NATIVE,
            runtime_id="test_runtime",
            name="Test Runtime",
        )

        runtime = Mock(spec=AgentRuntime)
        runtime.runtime_id = "test_runtime"
        runtime.runtime_type = RuntimeType.NATIVE
        runtime.capabilities = RuntimeCapabilities()
        runtime.status = RuntimeStatus.STOPPED

        info = mock_registry.register(runtime, config)

        assert info.runtime_id == "test_runtime"
        assert info.name == "Test Runtime"
        assert info.runtime_type == RuntimeType.NATIVE
        assert info.status == RuntimeStatus.STOPPED

        # Check it's in the registry
        retrieved = mock_registry.get_runtime("test_runtime")
        assert retrieved == runtime

    @pytest.mark.asyncio
    async def test_list_runtimes(self, mock_registry):
        """Test listing runtimes."""
        config1 = RuntimeConfig(
            runtime_type=RuntimeType.NATIVE,
            runtime_id="native_1",
            name="Native 1",
        )
        config2 = RuntimeConfig(
            runtime_type=RuntimeType.HERMES,
            runtime_id="hermes_1",
            name="Hermes 1",
        )

        runtime1 = Mock(spec=AgentRuntime)
        runtime1.runtime_id = "native_1"
        runtime1.runtime_type = RuntimeType.NATIVE
        runtime1.capabilities = RuntimeCapabilities()
        runtime1.status = RuntimeStatus.STOPPED

        runtime2 = Mock(spec=AgentRuntime)
        runtime2.runtime_id = "hermes_1"
        runtime2.runtime_type = RuntimeType.HERMES
        runtime2.capabilities = RuntimeCapabilities()
        runtime2.status = RuntimeStatus.STOPPED

        mock_registry.register(runtime1, config1)
        mock_registry.register(runtime2, config2)

        # List all
        all_runtimes = mock_registry.list_runtimes()
        assert len(all_runtimes) == 2

        # Filter by type
        native_runtimes = mock_registry.list_runtimes(runtime_type=RuntimeType.NATIVE)
        assert len(native_runtimes) == 1
        assert native_runtimes[0].runtime_id == "native_1"

        hermes_runtimes = mock_registry.list_runtimes(runtime_type=RuntimeType.HERMES)
        assert len(hermes_runtimes) == 1
        assert hermes_runtimes[0].runtime_id == "hermes_1"

    @pytest.mark.asyncio
    async def test_update_status(self, mock_registry):
        """Test updating runtime status."""
        config = RuntimeConfig(
            runtime_type=RuntimeType.NATIVE,
            runtime_id="test_runtime",
            name="Test Runtime",
        )

        runtime = Mock(spec=AgentRuntime)
        runtime.runtime_id = "test_runtime"
        runtime.runtime_type = RuntimeType.NATIVE
        runtime.capabilities = RuntimeCapabilities()
        runtime.status = RuntimeStatus.STOPPED

        mock_registry.register(runtime, config)

        # Update status
        updated = mock_registry.update_status("test_runtime", RuntimeStatus.RUNNING)
        assert updated.status == RuntimeStatus.RUNNING
        assert updated.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_start_stop_runtime(self, mock_registry):
        """Test starting and stopping runtime."""
        config = RuntimeConfig(
            runtime_type=RuntimeType.NATIVE,
            runtime_id="test_runtime",
            name="Test Runtime",
        )

        runtime = Mock(spec=AgentRuntime)
        runtime.runtime_id = "test_runtime"
        runtime.runtime_type = RuntimeType.NATIVE
        runtime.capabilities = RuntimeCapabilities()
        runtime.status = RuntimeStatus.STOPPED
        runtime.start = AsyncMock(return_value=True)
        runtime.stop = AsyncMock(return_value=True)

        mock_registry.register(runtime, config)

        # Start runtime
        info = await mock_registry.start_runtime("test_runtime")
        assert info.status == RuntimeStatus.RUNNING
        assert info.started_at is not None

        # Stop runtime
        result = await mock_registry.stop_runtime("test_runtime")
        assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])