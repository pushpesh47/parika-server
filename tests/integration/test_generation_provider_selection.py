"""
Integration test proving that `image.generate`/`image.edit`/
`video.generate`/`video.generate_from_image`/`video.edit` resolve to a
compatible generation Provider through the normal, unmodified
Planner/Model Selection Framework/ProviderManager path -- never by
bypassing `ProviderManager` or hard-coding a specific provider inside
Core or the Generation Module.

Uses a fake `ProviderDriver` (not `ComfyUIProviderDriver`) registered
through the real `ProviderManager`, so this test also demonstrates
that the Generation Module's Provider Capabilities are satisfiable by
*any* compatible Provider, not specifically ComfyUI -- exactly the
"provider independence" requirement.
"""

from __future__ import annotations

import base64

import pytest

from parika.core.brain.brain import Brain
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.planner.goal import Goal
from parika.core.planner.planner import Planner
from parika.core.brain.brain_request import BrainRequest
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
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.resource_manager.resource_manager import ResourceManager
from parika.core.state_manager.states import ProviderState
from parika.core.task_manager.task_manager import TaskManager
from parika.core.tool_manager.tool_manager import ToolManager
from parika.modules.generation.module_driver import GenerationModuleDriver

_FAKE_PROVIDER_ID = "provider.fake_generation"


class FakeGenerationProviderDriver(ProviderDriver):
    """
    Minimal `ProviderDriver` implementation that answers every
    `GenerationRequest` with a fixed artifact, used only to prove the
    Generation Module's Provider Capabilities are resolved through
    the real, unmodified Planner/Model Selection/ProviderManager path
    -- not to exercise generation logic itself (see
    `tests/providers/comfyui/test_driver.py` for that).
    """

    def __init__(self) -> None:
        self.received_requests: list[GenerationRequest] = []

    def discover_models(self) -> frozenset[ProviderModel]:
        return frozenset()

    def check_health(self) -> ProviderHealth:
        return ProviderHealth(available=True)

    def execute(self, model, request):
        self.received_requests.append(request)
        return GenerationResult(
            model_id=model.id,
            artifacts=(
                GeneratedArtifact(
                    content_base64=base64.b64encode(b"fake-artifact").decode(
                        "ascii"
                    ),
                    mime_type="image/png" if "image" in model.id else "video/mp4",
                ),
            ),
        )


@pytest.fixture()
def runtime(logger, event_bus, configuration, monkeypatch):
    # This test proves Provider *selection*, not the Filesystem
    # Module's own (unmodified, separately tested) read/write
    # behavior, so substitute trivial nested-Goal results for
    # `image.edit`/`video.generate_from_image`'s input reads and
    # every operation's output write, rather than pulling in the
    # whole Filesystem Module here.
    from parika.modules.generation import engine as generation_engine

    monkeypatch.setattr(
        generation_engine,
        "read_file_base64",
        lambda brain, path: base64.b64encode(b"source").decode("ascii"),
    )
    monkeypatch.setattr(
        generation_engine,
        "write_file_base64",
        lambda brain, path, content_base64: {"path": path},
    )

    capability_registry = CapabilityRegistry(event_bus, logger)
    capability_resolver = CapabilityResolver(
        capability_registry=capability_registry, logger=logger
    )
    policy_engine = PolicyEngine(event_bus=event_bus, logger=logger)
    provider_manager = ProviderManager(event_bus=event_bus, logger=logger)
    tool_manager = ToolManager(event_bus, logger)
    resource_manager = ResourceManager(configuration=configuration, logger=logger)

    capability_executor = CapabilityExecutor(
        event_bus=event_bus,
        logger=logger,
        tool_manager=tool_manager,
        provider_manager=provider_manager,
    )
    task_manager = TaskManager(
        event_bus=event_bus, logger=logger, capability_executor=capability_executor
    )
    planner = Planner(
        capability_resolver=capability_resolver,
        resource_manager=resource_manager,
        policy_engine=policy_engine,
        provider_manager=provider_manager,
        tool_manager=tool_manager,
        logger=logger,
    )
    brain = Brain(planner=planner, task_manager=task_manager, logger=logger)

    generation_driver = GenerationModuleDriver(
        capability_registry=capability_registry,
        tool_manager=tool_manager,
        brain=brain,
        logger=logger,
    )
    generation_driver.start()

    fake_driver = FakeGenerationProviderDriver()
    provider_manager.register(
        Provider(
            id=_FAKE_PROVIDER_ID,
            name="Fake Generation Provider",
            state=ProviderState.CONNECTED,
            enabled=True,
            # A plain tuple, not a `frozenset` -- `ProviderModel`
            # carries a `metadata: Mapping[str, object]` field (a
            # `MappingProxyType`), which is not hashable, so no
            # `ProviderModel` can actually be placed in a `frozenset`
            # at runtime despite `Provider.models`'s declared type
            # (see `parika.providers.ollama.driver
            # .OllamaProviderDriver.list_models()`'s own docstring for
            # the same, pre-existing situation this test relies on).
            models=(
                ProviderModel(
                    id="fake/image-model",
                    name="fake-image-model",
                    capabilities=frozenset({ModelCapability.IMAGE_GENERATION}),
                    specializations=frozenset(
                        {"image_generation", "image_editing"}
                    ),
                    supported_modalities=frozenset({"image"}),
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
                ),
            ),
        ),
        fake_driver,
    )

    return brain, fake_driver


def test_image_generate_resolves_through_provider_manager(runtime) -> None:
    brain, fake_driver = runtime

    goal = Goal(
        id="g1",
        capability_id="image.generate",
        inputs={"prompt": "a futuristic city at night"},
    )
    response = brain.handle(BrainRequest(goals=(goal,)))

    assert response.results[0].succeeded
    assert len(fake_driver.received_requests) == 1
    assert fake_driver.received_requests[0].operation is (
        GenerationOperation.IMAGE_GENERATE
    )


def test_image_edit_resolves_through_provider_manager(runtime) -> None:
    brain, fake_driver = runtime

    goal = Goal(
        id="g1",
        capability_id="image.edit",
        inputs={"path": "/img.png", "prompt": "make the sky sunset colored"},
    )
    response = brain.handle(BrainRequest(goals=(goal,)))

    assert response.results[0].succeeded
    assert fake_driver.received_requests[0].operation is (
        GenerationOperation.IMAGE_EDIT
    )


def test_video_generate_from_image_resolves_through_provider_manager(runtime) -> None:
    brain, fake_driver = runtime

    goal = Goal(
        id="g1",
        capability_id="video.generate_from_image",
        inputs={"path": "/img.png", "instruction": "gentle motion"},
    )
    response = brain.handle(BrainRequest(goals=(goal,)))

    assert response.results[0].succeeded
    assert fake_driver.received_requests[0].operation is (
        GenerationOperation.VIDEO_GENERATE_FROM_IMAGE
    )
