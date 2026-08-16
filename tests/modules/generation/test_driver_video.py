"""
Unit tests for `parika.modules.generation.driver_video`, using
`FakeBrain`.
"""

from __future__ import annotations

import pytest

from parika.core.tool_manager.request import ToolRequest
from parika.modules.generation.config import GenerationToolConfig
from parika.modules.generation.driver_video import (
    VideoEditToolDriver,
    VideoGenerateFromImageToolDriver,
    VideoGenerateToolDriver,
)
from parika.modules.generation.exceptions import GenerationInputReadError

from .conftest import generation_result, read_result, write_result


class TestVideoGenerateToolDriver:
    def test_generates_and_writes_default_output_path(self, fake_brain) -> None:
        fake_brain.queue(
            "video.provider_generate",
            generation_result(mime_type="video/mp4"),
        )
        fake_brain.queue("filesystem.write", write_result())

        driver = VideoGenerateToolDriver(
            brain=fake_brain,
            provider_capability_id="video.provider_generate",
            config=GenerationToolConfig(output_directory="generated"),
        )
        response = driver.execute(
            ToolRequest(
                arguments={
                    "prompt": "a spaceship flying through a nebula",
                    "duration_seconds": 5,
                }
            )
        )

        assert response.result["output_path"].startswith("generated/video_generate_")
        assert response.result["output_path"].endswith(".mp4")

        goal = fake_brain.goals_for("video.provider_generate")[0]
        assert goal.metadata["execution_requirements"]["task_category"] == (
            "video_generation"
        )

    def test_raises_when_prompt_missing(self, fake_brain) -> None:
        driver = VideoGenerateToolDriver(
            brain=fake_brain,
            provider_capability_id="video.provider_generate",
            config=GenerationToolConfig(),
        )

        with pytest.raises(GenerationInputReadError):
            driver.execute(ToolRequest(arguments={}))


class TestVideoGenerateFromImageToolDriver:
    def test_animates_image_into_video(self, fake_brain) -> None:
        fake_brain.queue("filesystem.read", read_result())
        fake_brain.queue(
            "video.provider_generate_from_image",
            generation_result(mime_type="video/mp4"),
        )
        fake_brain.queue("filesystem.write", write_result())

        driver = VideoGenerateFromImageToolDriver(
            brain=fake_brain,
            provider_capability_id="video.provider_generate_from_image",
            config=GenerationToolConfig(output_directory="generated"),
        )
        response = driver.execute(
            ToolRequest(arguments={"path": "/img.png", "instruction": "gentle motion"})
        )

        assert response.result["output_path"].startswith(
            "generated/video_generate_from_image_"
        )

        goal = fake_brain.goals_for("video.provider_generate_from_image")[0]
        assert goal.metadata["execution_requirements"]["task_category"] == (
            "video_generation_from_image"
        )

    def test_raises_when_path_missing(self, fake_brain) -> None:
        driver = VideoGenerateFromImageToolDriver(
            brain=fake_brain,
            provider_capability_id="video.provider_generate_from_image",
            config=GenerationToolConfig(),
        )

        with pytest.raises(GenerationInputReadError):
            driver.execute(ToolRequest(arguments={}))


class TestVideoEditToolDriver:
    def test_edits_existing_video(self, fake_brain) -> None:
        fake_brain.queue("filesystem.read", read_result())
        fake_brain.queue(
            "video.provider_edit",
            generation_result(mime_type="video/mp4"),
        )
        fake_brain.queue("filesystem.write", write_result())

        driver = VideoEditToolDriver(
            brain=fake_brain,
            provider_capability_id="video.provider_edit",
            config=GenerationToolConfig(output_directory="generated"),
        )
        response = driver.execute(
            ToolRequest(
                arguments={"path": "/video.mp4", "prompt": "oil painting style"}
            )
        )

        assert response.result["output_path"].startswith("generated/video_edit_")

        goal = fake_brain.goals_for("video.provider_edit")[0]
        assert goal.metadata["execution_requirements"]["task_category"] == (
            "video_editing"
        )

    def test_raises_when_prompt_missing(self, fake_brain) -> None:
        driver = VideoEditToolDriver(
            brain=fake_brain,
            provider_capability_id="video.provider_edit",
            config=GenerationToolConfig(),
        )

        with pytest.raises(GenerationInputReadError):
            driver.execute(ToolRequest(arguments={"path": "/video.mp4"}))

    def test_raises_when_path_missing(self, fake_brain) -> None:
        driver = VideoEditToolDriver(
            brain=fake_brain,
            provider_capability_id="video.provider_edit",
            config=GenerationToolConfig(),
        )

        with pytest.raises(GenerationInputReadError):
            driver.execute(ToolRequest(arguments={"prompt": "restyle it"}))
