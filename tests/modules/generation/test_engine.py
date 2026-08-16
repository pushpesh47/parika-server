"""
Unit tests for `parika.modules.generation.engine`.
"""

from __future__ import annotations

import pytest

from parika.core.planner.model_selection.requirements import ExecutionRequirements
from parika.core.provider_manager.generation_request import (
    GenerationOperation,
    GenerationRequest,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.modules.generation import engine
from parika.modules.generation.exceptions import (
    GenerationInputReadError,
    GenerationProviderError,
    GenerationWriteError,
)

from .conftest import ARTIFACT_BASE64, generation_result, read_result, write_result, failed_result


class TestReadWriteHelpers:
    def test_read_file_base64_returns_content(self, fake_brain) -> None:
        fake_brain.queue("filesystem.read", read_result())

        content = engine.read_file_base64(fake_brain, "/img.png")

        assert content

    def test_read_file_base64_raises_on_failure(self, fake_brain) -> None:
        fake_brain.queue("filesystem.read", failed_result("not found"))

        with pytest.raises(GenerationInputReadError):
            engine.read_file_base64(fake_brain, "/missing.png")

    def test_write_file_base64_raises_on_failure(self, fake_brain) -> None:
        fake_brain.queue("filesystem.write", failed_result("disk full"))

        with pytest.raises(GenerationWriteError):
            engine.write_file_base64(fake_brain, "/out.png", "Zm9v")


class TestExtensionForMimeType:
    @pytest.mark.parametrize(
        "mime_type,expected",
        [
            ("image/png", "png"),
            ("image/jpeg", "jpg"),
            ("video/mp4", "mp4"),
            ("video/webm", "webm"),
            ("application/octet-stream", "bin"),
        ],
    )
    def test_maps_known_mime_types(self, mime_type: str, expected: str) -> None:
        assert engine.extension_for_mime_type(mime_type) == expected


class TestGenerateWithProvider:
    def test_builds_generation_request_and_returns_result(self, fake_brain) -> None:
        fake_brain.queue("image.provider_generate", generation_result())

        result = engine.generate_with_provider(
            fake_brain,
            "image.provider_generate",
            operation=GenerationOperation.IMAGE_GENERATE,
            task_category="image_generation",
            prompt="a city at night",
        )

        assert result.artifacts[0].content_base64 == ARTIFACT_BASE64

        goal = fake_brain.goals_for("image.provider_generate")[0]
        built_request = goal.provider_request_builder(None, None)
        assert isinstance(built_request, GenerationRequest)
        assert built_request.operation is GenerationOperation.IMAGE_GENERATE
        assert built_request.prompt == "a city at night"

    def test_default_task_category_is_set_when_no_override_given(
        self, fake_brain
    ) -> None:
        fake_brain.queue("video.provider_generate", generation_result())

        engine.generate_with_provider(
            fake_brain,
            "video.provider_generate",
            operation=GenerationOperation.VIDEO_GENERATE,
            task_category="video_generation",
            prompt="a river flowing",
        )

        goal = fake_brain.goals_for("video.provider_generate")[0]
        assert goal.metadata["execution_requirements"] == {
            "task_category": "video_generation"
        }

    def test_caller_supplied_task_category_override_wins(self, fake_brain) -> None:
        fake_brain.queue("video.provider_generate", generation_result())

        engine.generate_with_provider(
            fake_brain,
            "video.provider_generate",
            operation=GenerationOperation.VIDEO_GENERATE,
            task_category="video_generation",
            prompt="a river flowing",
            execution_requirements={"task_category": "custom_override"},
        )

        goal = fake_brain.goals_for("video.provider_generate")[0]
        assert goal.metadata["execution_requirements"]["task_category"] == (
            "custom_override"
        )

    def test_execution_requirements_instance_passed_through_unchanged(
        self, fake_brain
    ) -> None:
        fake_brain.queue("video.provider_generate", generation_result())
        requirements = ExecutionRequirements(capability=ModelCapability.VIDEO_GENERATION)

        engine.generate_with_provider(
            fake_brain,
            "video.provider_generate",
            operation=GenerationOperation.VIDEO_GENERATE,
            task_category="video_generation",
            prompt="a river flowing",
            execution_requirements=requirements,
        )

        goal = fake_brain.goals_for("video.provider_generate")[0]
        assert goal.metadata["execution_requirements"] is requirements

    def test_raises_when_provider_goal_fails(self, fake_brain) -> None:
        fake_brain.queue("image.provider_generate", failed_result("no model"))

        with pytest.raises(GenerationProviderError):
            engine.generate_with_provider(
                fake_brain,
                "image.provider_generate",
                operation=GenerationOperation.IMAGE_GENERATE,
                task_category="image_generation",
                prompt="a cat",
            )
