"""
Tests for PARIKA Implementation Registry
"""

import pytest
from unittest.mock import Mock, MagicMock
from types import MappingProxyType

from parika.core.implementation_registry.implementation import (
    CapabilityImplementation,
    ImplementationSource,
    ImplementationStatus,
    ImplementationMetadata,
)
from parika.core.implementation_registry.implementation_registry import (
    ImplementationRegistry,
    ImplementationFilter,
)
from parika.core.implementation_registry.implementation_resolver import (
    ImplementationResolver,
    SelectionCandidate,
)


class TestImplementationMetadata:
    """Test implementation metadata."""

    def test_metadata_creation(self):
        """Test creating implementation metadata."""
        metadata = ImplementationMetadata(
            runtime_type="native",
            tool_ids=("tool1", "tool2"),
            skill_ids=("skill1",),
            required_capabilities=("cap1",),
            tags=("fast", "reliable"),
        )
        assert metadata.runtime_type == "native"
        assert metadata.tool_ids == ("tool1", "tool2")
        assert metadata.skill_ids == ("skill1",)
        assert metadata.tags == ("fast", "reliable")

    def test_metadata_to_dict(self):
        """Test metadata serialization."""
        metadata = ImplementationMetadata(
            runtime_type="hermes",
            tool_ids=("tool1",),
            tags=("hermes",),
        )
        d = metadata.to_dict()
        assert d["runtime_type"] == "hermes"
        assert d["tool_ids"] == ["tool1"]
        assert d["tags"] == ["hermes"]


class TestCapabilityImplementation:
    """Test capability implementation model."""

    def test_implementation_creation(self):
        """Test creating an implementation."""
        metadata = ImplementationMetadata(
            runtime_type="native",
            tool_ids=("tool1",),
        )
        impl = CapabilityImplementation.create(
            capability_id="filesystem.read",
            source=ImplementationSource.PARIKA_NATIVE,
            name="Native File Read",
            description="Native implementation of file read",
            version="1.0.0",
            metadata=metadata,
        )
        assert impl.id.startswith("impl_")
        assert impl.capability_id == "filesystem.read"
        assert impl.source == ImplementationSource.PARIKA_NATIVE
        assert impl.status == ImplementationStatus.REGISTERED

    def test_implementation_success_rate(self):
        """Test success rate calculation."""
        metadata = ImplementationMetadata(runtime_type="native")
        impl = CapabilityImplementation.create(
            capability_id="test",
            source=ImplementationSource.PARIKA_NATIVE,
            name="Test",
            description="Test",
            version="1.0.0",
            metadata=metadata,
        )
        # No usage yet
        assert impl.success_rate() == 0.5  # Default experience score

        # Record some successes
        impl = impl.record_success(100.0, 0.01)
        impl = impl.record_success(150.0, 0.02)
        impl = impl.record_failure("timeout")
        assert impl.usage_count == 3
        assert impl.success_count == 2
        assert impl.failure_count == 1
        assert abs(impl.success_rate() - 2/3) < 0.01

    def test_implementation_health(self):
        """Test implementation health check."""
        metadata = ImplementationMetadata(runtime_type="native")
        impl = CapabilityImplementation.create(
            capability_id="test",
            source=ImplementationSource.PARIKA_NATIVE,
            name="Test",
            description="Test",
            version="1.0.0",
            metadata=metadata,
        )
        # Not active yet
        assert not impl.is_healthy()

        # Active and healthy
        impl = CapabilityImplementation(
            id=impl.id,
            capability_id=impl.capability_id,
            source=impl.source,
            name=impl.name,
            description=impl.description,
            version=impl.version,
            metadata=impl.metadata,
            status=ImplementationStatus.ACTIVE,
            security_status="approved",
            reliability_score=0.8,
            created_at=impl.created_at,
            updated_at=impl.updated_at,
        )
        assert impl.is_healthy()

        # Blocked security
        impl = CapabilityImplementation(
            id=impl.id,
            capability_id=impl.capability_id,
            source=impl.source,
            name=impl.name,
            description=impl.description,
            version=impl.version,
            metadata=impl.metadata,
            status=ImplementationStatus.ACTIVE,
            security_status="blocked",
            reliability_score=0.8,
            created_at=impl.created_at,
            updated_at=impl.updated_at,
        )
        assert not impl.is_healthy()


class TestImplementationRegistry:
    """Test implementation registry."""

    @pytest.fixture
    def mock_registry(self):
        """Create a registry with mocked dependencies."""
        cap_registry = Mock()
        cap_registry.contains = Mock(return_value=True)

        tool_manager = Mock()
        tool_manager.contains = Mock(return_value=True)

        skill_registry = Mock()
        skill_registry.get_skill = Mock(return_value=Mock(is_activatable=Mock(return_value=True)))

        event_bus = Mock()
        logger = Mock()
        logger.get_logger = Mock(return_value=Mock(info=Mock(), debug=Mock(), warning=Mock(), error=Mock()))

        return ImplementationRegistry(
            capability_registry=cap_registry,
            tool_manager=tool_manager,
            skill_registry=skill_registry,
            event_bus=event_bus,
            logger=logger,
        )

    def test_register_implementation(self, mock_registry):
        """Test registering an implementation."""
        metadata = ImplementationMetadata(
            runtime_type="native",
            tool_ids=("tool1",),
            skill_ids=("skill1",),
        )

        impl = mock_registry.register_implementation(
            capability_id="filesystem.read",
            source=ImplementationSource.PARIKA_NATIVE,
            name="Native Read",
            description="Native file read",
            version="1.0.0",
            metadata=metadata,
        )

        assert impl.capability_id == "filesystem.read"
        assert impl.source == ImplementationSource.PARIKA_NATIVE
        assert impl.status == ImplementationStatus.REGISTERED

        # Check it's in the registry
        retrieved = mock_registry.get_implementation(impl.id)
        assert retrieved is not None
        assert retrieved.id == impl.id

    def test_get_implementations_for_capability(self, mock_registry):
        """Test getting implementations for a capability."""
        metadata = ImplementationMetadata(runtime_type="native", tool_ids=("tool1",))

        impl1 = mock_registry.register_implementation(
            capability_id="filesystem.read",
            source=ImplementationSource.PARIKA_NATIVE,
            name="Native Read",
            description="Native file read",
            version="1.0.0",
            metadata=metadata,
        )

        impl2 = mock_registry.register_implementation(
            capability_id="filesystem.read",
            source=ImplementationSource.HERMES,
            name="Hermes Read",
            description="Hermes file read",
            version="1.0.0",
            metadata=ImplementationMetadata(runtime_type="hermes", tool_ids=("tool1",)),
        )

        impls = mock_registry.get_implementations_for_capability("filesystem.read")
        assert len(impls) == 2

        # Filter by source
        native_impls = mock_registry.get_implementations_for_capability(
            "filesystem.read",
            source=ImplementationSource.PARIKA_NATIVE,
        )
        assert len(native_impls) == 1
        assert native_impls[0].id == impl1.id

    def test_list_implementations_with_filter(self, mock_registry):
        """Test listing implementations with filter."""
        metadata = ImplementationMetadata(runtime_type="native", tool_ids=("tool1",), tags=("fast",))

        impl1 = mock_registry.register_implementation(
            capability_id="cap1",
            source=ImplementationSource.PARIKA_NATIVE,
            name="Impl1",
            description="Impl1",
            version="1.0.0",
            metadata=metadata,
        )

        impl2 = mock_registry.register_implementation(
            capability_id="cap2",
            source=ImplementationSource.HERMES,
            name="Impl2",
            description="Impl2",
            version="1.0.0",
            metadata=ImplementationMetadata(runtime_type="hermes", tool_ids=("tool1",)),
        )

        # Filter by capability
        filter_cap = ImplementationFilter(capability_id="cap1")
        impls = mock_registry.list_implementations(filter_cap)
        assert len(impls) == 1
        assert impls[0].id == impl1.id

        # Filter by source
        filter_src = ImplementationFilter(source=ImplementationSource.HERMES)
        impls = mock_registry.list_implementations(filter_src)
        assert len(impls) == 1
        assert impls[0].id == impl2.id

        # Filter by runtime
        filter_rt = ImplementationFilter(runtime_type="native")
        impls = mock_registry.list_implementations(filter_rt)
        assert len(impls) == 1
        assert impls[0].id == impl1.id

    def test_update_status(self, mock_registry):
        """Test updating implementation status."""
        metadata = ImplementationMetadata(runtime_type="native", tool_ids=("tool1",))

        impl = mock_registry.register_implementation(
            capability_id="test",
            source=ImplementationSource.PARIKA_NATIVE,
            name="Test",
            description="Test",
            version="1.0.0",
            metadata=metadata,
        )

        # Update to active
        updated = mock_registry.update_implementation_status(impl.id, ImplementationStatus.ACTIVE)
        assert updated.status == ImplementationStatus.ACTIVE

        # Update with error
        updated = mock_registry.update_implementation_status(impl.id, ImplementationStatus.ERROR, "Failed to start")
        assert updated.status == ImplementationStatus.ERROR
        assert updated.error == "Failed to start"


class TestImplementationResolver:
    """Test implementation resolver (requires more mocking)."""

    def test_selection_candidate(self):
        """Test selection candidate creation."""
        metadata = ImplementationMetadata(runtime_type="native")
        impl = CapabilityImplementation.create(
            capability_id="test",
            source=ImplementationSource.PARIKA_NATIVE,
            name="Test",
            description="Test",
            version="1.0.0",
            metadata=metadata,
        )
        impl = CapabilityImplementation(
            id=impl.id,
            capability_id=impl.capability_id,
            source=impl.source,
            name=impl.name,
            description=impl.description,
            version=impl.version,
            metadata=impl.metadata,
            status=ImplementationStatus.ACTIVE,
            security_status="approved",
            experience_score=0.8,
            reliability_score=0.9,
            avg_latency_ms=100.0,
            avg_cost=0.01,
            created_at=impl.created_at,
            updated_at=impl.updated_at,
        )

        candidate = SelectionCandidate(
            implementation=impl,
            hard_gate_passed=True,
            gate_failures=(),
            fitness_score=0.85,
            score_breakdown=MappingProxyType({
                "experience": 0.8,
                "reliability": 0.9,
                "latency": 0.8,
                "cost": 0.5,
                "resource_efficiency": 1.0,
                "runtime_preference": 1.0,
            }),
        )

        assert candidate.implementation.id == impl.id
        assert candidate.hard_gate_passed is True
        assert candidate.fitness_score == 0.85


if __name__ == "__main__":
    pytest.main([__file__, "-v"])