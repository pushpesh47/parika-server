"""
Unit tests for `parika.modules.generation.driver_image`, using
`FakeBrain`.
"""

from __future__ import annotations

import base64

import pytest

from parika.core.provider_manager.generation_request import GenerationOperation
from parika.core.tool_manager.request import ToolRequest
from parika.modules.generation.config import GenerationToolConfig
from parika.modules.generation.driver_image import (
    ImageEditToolDriver,
    ImageGenerateToolDriver,
)
from parika.modules.generation.exceptions import GenerationInputReadError, GenerationProviderError

from .conftest import ARTIFACT_BASE64, generation_result, read_result, write_result, failed_result


class TestImageGenerateToolDriver:
    def test_generates_and_writes_default_output_path(self, fake_brain) -> None:
        fake_brain.queue("image.provider_generate", generation_result())
        fake_brain.queue("filesystem.write", write_result())

        driver = ImageGenerateToolDriver(
            brain=fake_brain,
            provider_capability_id="image.provider_generate",
            config=GenerationToolConfig(output_directory="generated"),
        )
        response = driver.execute(
            ToolRequest(arguments={"prompt": "a futuristic city at night"})
        )

        assert response.result["output_path"].startswith("generated/image_generate_")
        assert response.result["output_path"].endswith(".png")

        generate_goal = fake_brain.goals_for("image.provider_generate")[0]
        assert generate_goal.metadata["execution_requirements"]["task_category"] == (
            "image_generation"
        )

        write_goal = fake_brain.goals_for("filesystem.write")[0]
        assert write_goal.inputs["content_base64"] == ARTIFACT_BASE64

    def test_honors_explicit_output_path(self, fake_brain) -> None:
        fake_brain.queue("image.provider_generate", generation_result())
        fake_brain.queue("filesystem.write", write_result())

        driver = ImageGenerateToolDriver(
            brain=fake_brain,
            provider_capability_id="image.provider_generate",
            config=GenerationToolConfig(),
        )
        response = driver.execute(
            ToolRequest(
                arguments={"prompt": "a red kite", "output_path": "/out/kite.png"}
            )
        )

        assert response.result["output_path"] == "/out/kite.png"

    def test_raises_when_prompt_missing(self, fake_brain) -> None:
        driver = ImageGenerateToolDriver(
            brain=fake_brain,
            provider_capability_id="image.provider_generate",
            config=GenerationToolConfig(),
        )

        with pytest.raises(GenerationInputReadError):
            driver.execute(ToolRequest(arguments={}))

    def test_raises_when_provider_fails(self, fake_brain) -> None:
        fake_brain.queue("image.provider_generate", failed_result("no model available"))

        driver = ImageGenerateToolDriver(
            brain=fake_brain,
            provider_capability_id="image.provider_generate",
            config=GenerationToolConfig(),
        )

        with pytest.raises(GenerationProviderError):
            driver.execute(ToolRequest(arguments={"prompt": "a cat"}))


class TestImageEditToolDriver:
    def test_edits_and_writes_output(self, fake_brain) -> None:
        fake_brain.queue("filesystem.read", read_result())
        fake_brain.queue("image.provider_edit", generation_result())
        fake_brain.queue("filesystem.write", write_result())

        driver = ImageEditToolDriver(
            brain=fake_brain,
            provider_capability_id="image.provider_edit",
            config=GenerationToolConfig(output_directory="generated"),
        )
        response = driver.execute(
            ToolRequest(
                arguments={"path": "/img.png", "prompt": "make the sky sunset colored"}
            )
        )

        assert response.result["output_path"].startswith("generated/image_edit_")

        edit_goal = fake_brain.goals_for("image.provider_edit")[0]
        assert edit_goal.metadata["execution_requirements"]["task_category"] == (
            "image_editing"
        )

        read_goal = fake_brain.goals_for("filesystem.read")[0]
        assert read_goal.inputs["path"] == "/img.png"

    def test_raises_when_path_missing(self, fake_brain) -> None:
        driver = ImageEditToolDriver(
            brain=fake_brain,
            provider_capability_id="image.provider_edit",
            config=GenerationToolConfig(),
        )

        with pytest.raises(GenerationInputReadError):
            driver.execute(ToolRequest(arguments={"prompt": "remove the dog"}))

    def test_raises_when_prompt_missing(self, fake_brain) -> None:
        driver = ImageEditToolDriver(
            brain=fake_brain,
            provider_capability_id="image.provider_edit",
            config=GenerationToolConfig(),
        )

        with pytest.raises(GenerationInputReadError):
            driver.execute(ToolRequest(arguments={"path": "/img.png"}))
