"""
Unit tests for `VisionFindSimilarImagesToolDriver`/`VisionFindDuplicatesToolDriver`/
`VisionSearchImagesToolDriver` (`parika.modules.vision.driver_collection`),
using `FakeBrain`.
"""

from __future__ import annotations

import base64
import io

import pytest
from PIL import Image, ImageDraw

from parika.core.tool_manager.request import ToolRequest
from parika.modules.vision.driver_collection import (
    VisionFindDuplicatesToolDriver,
    VisionFindSimilarImagesToolDriver,
    VisionSearchImagesToolDriver,
)
from parika.modules.vision.exceptions import VisionImageReadError

from .conftest import analysis_result, read_result


def _b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _base() -> Image.Image:
    image = Image.new("RGB", (100, 100), color=(255, 255, 255))
    ImageDraw.Draw(image).rectangle([10, 10, 40, 40], fill=(0, 0, 0))
    return image


class TestVisionFindSimilarImagesToolDriver:
    def test_ranks_candidates_by_similarity(self, fake_brain) -> None:
        reference = _base()
        similar = reference.copy()
        different = Image.new("RGB", (100, 100), color=(0, 0, 0))

        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(reference)})
        )
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(similar)}))
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(different)})
        )

        driver = VisionFindSimilarImagesToolDriver(
            brain=fake_brain,
            provider_capability_id="vision.provider_find_similar_images",
        )

        response = driver.execute(
            ToolRequest(
                arguments={
                    "reference_path": "/ref.png",
                    "paths": ["/similar.png", "/different.png"],
                }
            )
        )

        matches = response.result["matches"]
        assert matches[0]["path"] == "/similar.png"
        assert matches[0]["overall_similarity"] >= matches[1]["overall_similarity"]
        assert fake_brain.goals_for("vision.provider_find_similar_images") == []

    def test_raises_when_reference_path_missing(self, fake_brain) -> None:
        driver = VisionFindSimilarImagesToolDriver(
            brain=fake_brain,
            provider_capability_id="vision.provider_find_similar_images",
        )

        with pytest.raises(VisionImageReadError):
            driver.execute(ToolRequest(arguments={"paths": ["/a.png"]}))

    def test_raises_when_no_candidate_set_given(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_base())})
        )

        driver = VisionFindSimilarImagesToolDriver(
            brain=fake_brain,
            provider_capability_id="vision.provider_find_similar_images",
        )

        with pytest.raises(VisionImageReadError):
            driver.execute(ToolRequest(arguments={"reference_path": "/ref.png"}))


class TestVisionFindDuplicatesToolDriver:
    def test_groups_near_identical_images(self, fake_brain) -> None:
        a = _base()
        b = a.copy()
        unrelated = Image.new("RGB", (100, 100), color=(0, 255, 0))

        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(a)}))
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(b)}))
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(unrelated)})
        )

        driver = VisionFindDuplicatesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_find_duplicates"
        )

        response = driver.execute(
            ToolRequest(arguments={"paths": ["/a.png", "/b.png", "/unrelated.png"]})
        )

        groups = response.result["duplicate_groups"]
        assert len(groups) == 1
        assert set(groups[0]["paths"]) == {"/a.png", "/b.png"}

    def test_uses_directory_via_filesystem_list(self, fake_brain) -> None:
        from .conftest import list_result

        image = _base()
        fake_brain.queue(
            "filesystem.list",
            list_result(
                [
                    {"path": "/dir/a.png", "name": "a.png", "is_file": True},
                    {"path": "/dir/readme.txt", "name": "readme.txt", "is_file": True},
                ]
            ),
        )
        fake_brain.queue("filesystem.read", read_result({"content_base64": _b64(image)}))

        driver = VisionFindDuplicatesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_find_duplicates"
        )

        response = driver.execute(ToolRequest(arguments={"directory": "/dir"}))

        assert response.result["images_checked"] == 1


class TestVisionSearchImagesToolDriver:
    def test_collects_matches_from_model_responses(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_base())})
        )
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_base())})
        )
        fake_brain.queue(
            "vision.provider_search_images",
            analysis_result("MATCH this is a red car."),
        )
        fake_brain.queue(
            "vision.provider_search_images",
            analysis_result("NO_MATCH not related."),
        )

        driver = VisionSearchImagesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_search_images"
        )

        response = driver.execute(
            ToolRequest(
                arguments={"query": "a red car", "paths": ["/one.png", "/two.png"]}
            )
        )

        assert response.result["matches"] == [
            {"path": "/one.png", "justification": "MATCH this is a red car."}
        ]
        assert response.result["candidates_checked"] == 2

    def test_respects_max_candidates_cap(self, fake_brain) -> None:
        fake_brain.queue(
            "filesystem.read", read_result({"content_base64": _b64(_base())})
        )
        fake_brain.queue(
            "vision.provider_search_images", analysis_result("NO_MATCH.")
        )

        driver = VisionSearchImagesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_search_images"
        )

        response = driver.execute(
            ToolRequest(
                arguments={
                    "query": "anything",
                    "paths": ["/one.png", "/two.png", "/three.png"],
                    "max_candidates": 1,
                }
            )
        )

        assert response.result["candidates_checked"] == 1
        assert response.result["candidates_available"] == 3

    def test_raises_when_query_missing(self, fake_brain) -> None:
        driver = VisionSearchImagesToolDriver(
            brain=fake_brain, provider_capability_id="vision.provider_search_images"
        )

        with pytest.raises(VisionImageReadError):
            driver.execute(ToolRequest(arguments={"paths": ["/a.png"]}))
