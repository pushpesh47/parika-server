"""
Regression test for image.provider_generate agent resolution.

This test verifies that the Vision Agent can resolve and execute
generation provider capabilities (image.provider_generate, video.provider_generate, etc.)
through the nested Brain call pattern used by the Generation Module.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import pytest

from parika.core.agent_orchestrator.agent_profile import AgentProfile
from parika.core.agent_orchestrator.agent_registry import AgentRegistry
from parika.core.agent_orchestrator.agent_resolver import AgentResolver
from parika.core.agent_orchestrator.agent_orchestrator import AgentOrchestrator
from parika.core.agent_orchestrator.agent_specialization import AgentSpecialization
from parika.core.brain.brain import Brain
from parika.core.brain.brain_request import BrainRequest
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import CapabilityDefinition
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.planner.planner import Planner
from parika.core.policy_engine.policy_engine import PolicyEngine
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.generation_request import (
    GenerationOperation,
    GenerationRequest,
)
from parika.core.provider_manager.generation_result import (
    GeneratedArtifact,
    GenerationResult,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.model_limits import ModelLimits
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.state_manager.states import ProviderState
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.tool_manager.response import ToolResponse
from parika.core.configuration.configuration import Configuration
from parika.core.planner.goal import Goal
from parika.modules.generation import engine as generation_engine


class _FakeGenerationProviderDriver(ProviderDriver):
    """Minimal provider driver that returns a fixed generation result."""

    def __init__(self) -> None:
        self.received_requests: list[GenerationRequest] = []

    def discover_models(self) -> frozenset[ProviderModel]:
        return frozenset()

    def check_health(self) -> ProviderHealth:
        return ProviderHealth(available=True)

    def execute(self, model: ProviderModel, request: object) -> GenerationResult:
        self.received_requests.append(request)
        return GenerationResult(
            model_id=model.id,
            artifacts=(
                GeneratedArtifact(
                    content_base64=base64.b64encode(b"fake-artifact").decode("ascii"),
                    mime_type="image/png",
                ),
            ),
        )


class _FakeVisionProviderDriver(ProviderDriver):
    """Minimal provider driver that returns a fixed vision result."""

    def __init__(self) -> None:
        self.received_requests: list[object] = []

    def discover_models(self) -> frozenset[ProviderModel]:
        return frozenset()

    def check_health(self) -> ProviderHealth:
        return ProviderHealth(available=True)

    def execute(self, model: ProviderModel, request: object) -> object:
        self.received_requests.append(request)
        from parika.core.provider_manager.chat_result import ChatResult
        from parika.core.provider_manager.chat_message import ChatMessage
        return ChatResult(message=ChatMessage(role="assistant", content="fake vision response"))


def _mock_read_file_base64(brain: Brain, path: str) -> str:
    return base64.b64encode(b"source").decode("ascii")


def _mock_write_file_base64(brain: Brain, path: str, content_base64: str) -> dict:
    return {"path": path}


@dataclass(frozen=True, slots=True)
class _FakeChatRequest:
    prompt: str = ""


class TestGenerationProviderCapabilities:
    """
    Tests that generation provider capabilities are correctly resolved
    through the Vision Agent when using the nested Brain call pattern.
    """

    def setup_method(self) -> None:
        config = Configuration()
        config.load()
        self.logger = Logger(config)
        self.event_bus = EventBus(self.logger)

        self.capability_registry = CapabilityRegistry(self.event_bus, self.logger)
        self.capability_resolver = CapabilityResolver(
            capability_registry=self.capability_registry,
            logger=self.logger,
        )

        self.agent_registry = AgentRegistry(self.event_bus, self.logger)
        self.agent_resolver = AgentResolver(
            agent_registry=self.agent_registry,
            capability_registry=self.capability_registry,
            logger=self.logger,
        )

        self.resource_manager = ResourceManager(configuration=config, logger=self.logger)
        self.policy_engine = PolicyEngine(event_bus=self.event_bus, logger=self.logger)
        self.provider_manager = ProviderManager(event_bus=self.event_bus, logger=self.logger)
        self.tool_manager = ToolManager(event_bus=self.event_bus, logger=self.logger)

        # Register fake generation provider
        self.gen_driver = _FakeGenerationProviderDriver()
        self.provider_manager.register(
            Provider(
                id="provider.fake_generation",
                name="Fake Generation Provider",
                state=ProviderState.CONNECTED,
                enabled=True,
                models=(
                    ProviderModel(
                        id="fake/image-model",
                        name="fake-image-model",
                        capabilities=frozenset({ModelCapability.IMAGE_GENERATION}),
                        specializations=frozenset({"image_generation", "image_editing"}),
                        supported_modalities=frozenset({"image"}),
                        limits=ModelLimits(context_window=8192),
                    ),
                    ProviderModel(
                        id="fake/video-model",
                        name="fake-video-model",
                        capabilities=frozenset({ModelCapability.VIDEO_GENERATION}),
                        specializations=frozenset(
                            {
                                "video_generation",
                                "video_generation_from_image",
                                "video_editing",
                            }
                        ),
                        supported_modalities=frozenset({"video"}),
                        limits=ModelLimits(context_window=8192),
                    ),
                ),
            ),
            self.gen_driver,
        )

        # Register fake vision provider for vision.provider_* capabilities
        self.vision_driver = _FakeVisionProviderDriver()
        self.provider_manager.register(
            Provider(
                id="provider.fake_vision",
                name="Fake Vision Provider",
                state=ProviderState.CONNECTED,
                enabled=True,
                models=(
                    ProviderModel(
                        id="fake/vision-model",
                        name="fake-vision-model",
                        capabilities=frozenset({ModelCapability.VISION}),
                        specializations=frozenset({"vision_understanding"}),
                        supported_modalities=frozenset({"image"}),
                        limits=ModelLimits(context_window=8192),
                    ),
                ),
            ),
            self.vision_driver,
        )

        self.planner = Planner(
            capability_resolver=self.capability_resolver,
            resource_manager=self.resource_manager,
            policy_engine=self.policy_engine,
            provider_manager=self.provider_manager,
            tool_manager=self.tool_manager,
            logger=self.logger,
            configuration=config,
        )

        self.capability_executor = CapabilityExecutor(
            event_bus=self.event_bus,
            logger=self.logger,
            tool_manager=self.tool_manager,
            provider_manager=self.provider_manager,
        )

        self.task_manager = TaskManager(
            event_bus=self.event_bus,
            logger=self.logger,
            capability_executor=self.capability_executor,
        )

        self.agent_orchestrator = AgentOrchestrator(
            planner=self.planner,
            task_manager=self.task_manager,
            agent_registry=self.agent_registry,
            agent_resolver=self.agent_resolver,
            capability_registry=self.capability_registry,
            logger=self.logger,
            event_bus=self.event_bus,
        )

        self.brain = Brain(
            planner=self.planner,
            task_manager=self.task_manager,
            logger=self.logger,
            event_bus=self.event_bus,
            agent_orchestrator=self.agent_orchestrator,
        )

        # Mock filesystem operations in the generation engine
        generation_engine.read_file_base64 = _mock_read_file_base64
        generation_engine.write_file_base64 = _mock_write_file_base64

        # Register modules FIRST so capabilities exist
        self._register_generation_module()
        self._register_vision_module()

        # Then register agents with full capability knowledge
        self._register_vision_agent()
        self._register_general_agent()

    def _register_vision_agent(self) -> None:
        """Register the Vision Agent with provider capability wildcard patterns."""
        def has_cap(cap_id: str) -> bool:
            return self.capability_registry.contains(cap_id)

        vision_caps = frozenset()
        vision_allowed = frozenset()
        vision_categories = frozenset(
            {
                CapabilityCategory.VISION,
                CapabilityCategory.OCR,
                CapabilityCategory.IMAGE_GENERATION,
                CapabilityCategory.VIDEO_GENERATION,
            }
        )

        vision_cap_ids = [
            "vision.describe_image",
            "vision.detect_objects",
            "vision.compare_images",
            "ocr.extract_text",
            "ocr.provider_extract_text",
            "document.read_pdf",
            "document.extract_text",
            "video.generate",
            "video.edit",
            "image.generate",
            "image.edit",
        ]
        for cap in vision_cap_ids:
            if has_cap(cap):
                vision_caps = vision_caps.union({cap})
                vision_allowed = vision_allowed.union({cap})

        # Add wildcard patterns for provider capabilities (the fix)
        vision_allowed = vision_allowed.union({
            "vision.provider_*",
            "image.provider_*",
            "video.provider_*",
        })

        from types import MappingProxyType
        self.agent_registry.register(AgentProfile(
            id="agent.vision",
            name="Vision Agent",
            specialization=AgentSpecialization.VISION,
            preferred_capabilities=vision_caps,
            allowed_capabilities=vision_allowed.union({"filesystem.read", "web.search"}),
            preferred_categories=vision_categories,
            allowed_categories=frozenset({
                CapabilityCategory.VISION,
                CapabilityCategory.OCR,
                CapabilityCategory.IMAGE_GENERATION,
                CapabilityCategory.VIDEO_GENERATION,
                CapabilityCategory.TOOL,
                CapabilityCategory.FILESYSTEM,
            }),
            preferred_models=frozenset({"llava", "bakllava", "moondream"}),
            behavioral_policies=MappingProxyType({
                "detail_level": "comprehensive",
                "visual_reasoning": True,
            }),
            delegation_policy="allow",
            metadata={"description": "Specialized for visual understanding and generation tasks"},
        ))

    def _register_general_agent(self) -> None:
        """Register the General Agent for chat.respond."""
        from types import MappingProxyType
        self.agent_registry.register(AgentProfile(
            id="agent.general",
            name="General Agent",
            specialization=AgentSpecialization.GENERAL,
            preferred_capabilities=frozenset({"chat.respond"}),
            allowed_capabilities=frozenset({"chat.respond"}),
            preferred_categories=frozenset({CapabilityCategory.LLM}),
            allowed_categories=frozenset({CapabilityCategory.LLM}),
            delegation_policy="allow",
            metadata={"description": "Handles general conversational LLM tasks (chat.respond)"},
        ))

    def _register_generation_module(self) -> None:
        """Register the Generation Module's capabilities and tools."""
        from parika.modules.generation.module_driver import GenerationModuleDriver
        gen_driver = GenerationModuleDriver(
            capability_registry=self.capability_registry,
            tool_manager=self.tool_manager,
            brain=self.brain,
            logger=self.logger,
        )
        gen_driver.start()

    def _register_vision_module(self) -> None:
        """Register the Vision Module's capabilities and tools."""
        from parika.modules.vision.module_driver import VisionModuleDriver
        vision_driver = VisionModuleDriver(
            capability_registry=self.capability_registry,
            tool_manager=self.tool_manager,
            brain=self.brain,
            logger=self.logger,
        )
        vision_driver.start()

    def test_agent_resolver_resolves_generation_provider_capabilities(self) -> None:
        """Test that the agent resolver can resolve generation provider capabilities."""
        # Modules already registered in setup_method
        # These should all resolve to agent.vision
        for cap_id in [
            "image.provider_generate",
            "image.provider_edit",
            "video.provider_generate",
            "video.provider_edit",
            "video.provider_generate_from_image",
        ]:
            resolution = self.agent_resolver.resolve(cap_id)
            assert resolution.agent.id == "agent.vision", \
                f"Expected agent.vision for {cap_id}, got {resolution.agent.id}"

    def test_agent_resolver_resolves_vision_provider_capabilities(self) -> None:
        """Test that the agent resolver can resolve vision provider capabilities."""
        # Modules already registered in setup_method
        # These should all resolve to agent.vision
        for cap_id in [
            "vision.provider_describe_image",
            "vision.provider_detect_objects",
            "vision.provider_answer_question",
            "vision.provider_analyze_scene",
        ]:
            resolution = self.agent_resolver.resolve(cap_id)
            assert resolution.agent.id == "agent.vision", \
                f"Expected agent.vision for {cap_id}, got {resolution.agent.id}"

    def test_image_generate_full_flow_through_agent_orchestrator(self) -> None:
        """Test the full image.generate -> image.provider_generate flow."""
        # Module already registered in setup_method
        goal = Goal(
            id="test-generate",
            capability_id="image.generate",
            inputs={"prompt": "a test image"},
        )
        request = BrainRequest(goals=(goal,))
        response = self.brain.handle(request)

        assert response.succeeded, f"Response failed: {response.results}"
        assert len(response.results) == 1
        assert response.results[0].succeeded
        assert response.results[0].capability_id == "image.generate"

        # Verify the provider was called
        assert len(self.gen_driver.received_requests) == 1
        assert self.gen_driver.received_requests[0].operation is GenerationOperation.IMAGE_GENERATE

    def test_image_edit_full_flow_through_agent_orchestrator(self) -> None:
        """Test the full image.edit -> image.provider_edit flow."""
        # Module already registered in setup_method
        goal = Goal(
            id="test-edit",
            capability_id="image.edit",
            inputs={"path": "/img.png", "prompt": "make it red"},
        )
        request = BrainRequest(goals=(goal,))
        response = self.brain.handle(request)

        assert response.succeeded, f"Response failed: {response.results}"
        assert len(response.results) == 1
        assert response.results[0].succeeded
        assert response.results[0].capability_id == "image.edit"

        # Verify the provider was called
        assert len(self.gen_driver.received_requests) == 1
        assert self.gen_driver.received_requests[0].operation is GenerationOperation.IMAGE_EDIT

    def test_video_generate_full_flow_through_agent_orchestrator(self) -> None:
        """Test the full video.generate -> video.provider_generate flow."""
        # Module already registered in setup_method
        goal = Goal(
            id="test-video-gen",
            capability_id="video.generate",
            inputs={"prompt": "a test video"},
        )
        request = BrainRequest(goals=(goal,))
        response = self.brain.handle(request)

        assert response.succeeded, f"Response failed: {response.results}"
        assert len(response.results) == 1
        assert response.results[0].succeeded
        assert response.results[0].capability_id == "video.generate"

        # Verify the provider was called
        assert len(self.gen_driver.received_requests) == 1
        assert self.gen_driver.received_requests[0].operation is GenerationOperation.VIDEO_GENERATE

    if __name__ == "__main__":
        pytest.main([__file__, "-v"])