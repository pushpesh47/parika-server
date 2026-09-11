"""
Tests for AutonomousTask contract and model.
"""

from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid4

import pytest

from parika.core.autonomous import (
    AutonomousTask,
    AutonomousTaskStatus,
    serialize_execution_requirements,
    deserialize_execution_requirements,
)
from parika.core.planner.model_selection.requirements import (
    ExecutionRequirements,
    ReasoningLevel,
    ModelCapability,
)


class TestAutonomousTaskContract:
    """Tests for AutonomousTask domain model."""

    def test_create_with_new_fields(self):
        """Test creating AutonomousTask with new provider execution fields."""
        now = datetime.now(UTC)
        task = AutonomousTask(
            id=uuid4().hex,
            mission_id=uuid4().hex,
            parent_task_id=None,
            agent_id=None,
            name="Test Task",
            description="Test Description",
            capability_id="vision.provider_describe_image",
            inputs=MappingProxyType({"instruction": "Describe this image", "images_base64": ["abc123"]}),
            status=AutonomousTaskStatus.CREATED,
            priority=0,
            progress=0.0,
            created_at=now,
            started_at=None,
            updated_at=now,
            completed_at=None,
            deadline=None,
            max_retries=3,
            retry_count=0,
            resource_budget=MappingProxyType({"max_runtime_seconds": 300}),
            checkpoint_id=None,
            result=None,
            failure=None,
            metadata=MappingProxyType({}),
            provider_request_type="vision",
            task_category="vision_understanding",
            execution_requirements=MappingProxyType({"capability": "vision"}),
        )

        assert task.provider_request_type == "vision"
        assert task.task_category == "vision_understanding"
        assert task.execution_requirements is not None
        assert task.execution_requirements.get("capability") == "vision"

    def test_create_without_optional_fields(self):
        """Test creating AutonomousTask without the new optional fields."""
        now = datetime.now(UTC)
        task = AutonomousTask(
            id=uuid4().hex,
            mission_id=uuid4().hex,
            parent_task_id=None,
            agent_id=None,
            name="Test Task",
            description="Test Description",
            capability_id="filesystem.read",
            inputs=MappingProxyType({"path": "/tmp/test.txt"}),
            status=AutonomousTaskStatus.CREATED,
            priority=0,
            progress=0.0,
            created_at=now,
            started_at=None,
            updated_at=now,
            completed_at=None,
            deadline=None,
            max_retries=3,
            retry_count=0,
            resource_budget=MappingProxyType({}),
            checkpoint_id=None,
            result=None,
            failure=None,
            metadata=MappingProxyType({}),
            provider_request_type=None,
            task_category=None,
            execution_requirements=None,
        )

        assert task.provider_request_type is None
        assert task.task_category is None
        assert task.execution_requirements is None

    def test_to_model_roundtrip(self):
        """Test AutonomousTask -> Model -> AutonomousTask roundtrip."""
        from parika.core.autonomous import AutonomousTaskModel

        now = datetime.now(UTC)
        task = AutonomousTask(
            id=uuid4().hex,
            mission_id=uuid4().hex,
            parent_task_id=None,
            agent_id=None,
            name="Test Task",
            description="Test Description",
            capability_id="vision.provider_describe_image",
            inputs=MappingProxyType({"instruction": "Describe", "images_base64": ["abc"]}),
            status=AutonomousTaskStatus.CREATED,
            priority=0,
            progress=0.0,
            created_at=now,
            started_at=None,
            updated_at=now,
            completed_at=None,
            deadline=None,
            max_retries=3,
            retry_count=0,
            resource_budget=MappingProxyType({}),
            checkpoint_id=None,
            result=None,
            failure=None,
            metadata=MappingProxyType({}),
            provider_request_type="vision",
            task_category="vision_understanding",
            execution_requirements=MappingProxyType({"capability": "vision"}),
        )

        model = task.to_model()
        restored = AutonomousTask.from_model(model)

        assert restored.id == task.id
        assert restored.provider_request_type == "vision"
        assert restored.task_category == "vision_understanding"
        assert restored.execution_requirements is not None


class TestExecutionRequirementsSerialization:
    """Tests for ExecutionRequirements serialization."""

    def test_serialize_basic(self):
        """Test serializing basic ExecutionRequirements."""
        req = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION,
            reasoning_level=ReasoningLevel.COMPLEX,
            task_category="general_chat",
            capability_id="chat.respond",
            required_specializations=frozenset({"general_chat"}),
            required_capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
            metadata={"test": "value"},
        )

        serialized = serialize_execution_requirements(req)

        assert serialized["capability"] == "text_generation"
        assert serialized["reasoning_level"] == "complex"
        assert serialized["task_category"] == "general_chat"
        assert serialized["capability_id"] == "chat.respond"
        assert serialized["required_specializations"] == ["general_chat"]
        assert serialized["required_capabilities"] == ["text_generation"]
        assert serialized["metadata"] == {"test": "value"}

    def test_deserialize_basic(self):
        """Test deserializing ExecutionRequirements."""
        data = {
            "capability": "text_generation",
            "reasoning_level": "complex",
            "task_category": "general_chat",
            "capability_id": "chat.respond",
            "required_specializations": ["general_chat"],
            "required_capabilities": ["text_generation"],
            "metadata": {"test": "value"},
        }

        req = deserialize_execution_requirements(data)

        assert req.capability == ModelCapability.TEXT_GENERATION
        assert req.reasoning_level == ReasoningLevel.COMPLEX
        assert req.task_category == "general_chat"
        assert req.capability_id == "chat.respond"
        assert req.required_specializations == frozenset({"general_chat"})
        assert req.required_capabilities == frozenset({ModelCapability.TEXT_GENERATION})
        assert req.metadata == MappingProxyType({"test": "value"})

    def test_roundtrip(self):
        """Test full serialize -> deserialize roundtrip."""
        original = ExecutionRequirements(
            capability=ModelCapability.VISION,
            reasoning_level=ReasoningLevel.NORMAL,
            task_category="vision_understanding",
            capability_id="vision.provider_describe_image",
            required_specializations=frozenset({"vision_understanding"}),
            required_capabilities=frozenset({ModelCapability.VISION}),
            required_modalities=frozenset({"image"}),
            metadata={"execution_requirements": {"custom": "data"}},
        )

        serialized = serialize_execution_requirements(original)
        restored = deserialize_execution_requirements(serialized)

        assert restored.capability == original.capability
        assert restored.reasoning_level == original.reasoning_level
        assert restored.task_category == original.task_category
        assert restored.capability_id == original.capability_id
        assert restored.required_specializations == original.required_specializations
        assert restored.required_capabilities == original.required_capabilities
        assert restored.required_modalities == original.required_modalities

    def test_excludes_available_resources(self):
        """Test that available_resources is excluded from serialization."""
        req = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION,
        )

        serialized = serialize_execution_requirements(req)

        assert "available_resources" not in serialized

    def test_frozenset_handling(self):
        """Test frozenset fields are serialized as lists and restored as frozensets."""
        req = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION,
            required_specializations=frozenset({"chat", "coding"}),
            required_modalities=frozenset({"text"}),
            capability_hints=frozenset({"current_datetime"}),
        )

        serialized = serialize_execution_requirements(req)
        restored = deserialize_execution_requirements(serialized)

        assert restored.required_specializations == frozenset({"chat", "coding"})
        assert restored.required_modalities == frozenset({"text"})
        assert restored.capability_hints == frozenset({"current_datetime"})
        assert isinstance(restored.required_specializations, frozenset)
        assert isinstance(restored.required_modalities, frozenset)
        assert isinstance(restored.capability_hints, frozenset)

    def test_enum_frozenset_handling(self):
        """Test frozenset[Enum] fields are handled correctly."""
        req = ExecutionRequirements(
            capability=ModelCapability.TEXT_GENERATION,
            required_capabilities=frozenset({
                ModelCapability.TEXT_GENERATION,
                ModelCapability.REASONING,
            }),
        )

        serialized = serialize_execution_requirements(req)
        restored = deserialize_execution_requirements(serialized)

        assert restored.required_capabilities == frozenset({
            ModelCapability.TEXT_GENERATION,
            ModelCapability.REASONING,
        })
        assert isinstance(restored.required_capabilities, frozenset)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])