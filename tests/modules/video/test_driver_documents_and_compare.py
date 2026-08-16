"""
Unit tests for the Video Module's document/slide/table
(`video.detect_documents`, `video.detect_slides`,
`video.extract_tables`), comparison (`video.compare_videos`,
`video.compare_frames`), and motion (`video.detect_motion`)
ToolDrivers, using a `FakeBrain` for every nested Provider Goal.
"""

from __future__ import annotations

import pytest

pytest.importorskip("cv2")

from parika.core.tool_manager.request import ToolRequest
from parika.modules.video.config import VideoToolConfig
from parika.modules.video.driver_compare_videos import VideoCompareVideosToolDriver
from parika.modules.video.driver_documents import (
    VideoDetectDocumentsToolDriver,
    VideoDetectSlidesToolDriver,
    VideoExtractTablesToolDriver,
)
from parika.modules.video.driver_motion import VideoCompareFramesToolDriver, VideoDetectMotionToolDriver

from .conftest import filesystem_info_result, provider_text_result


class TestVideoDetectDocumentsToolDriver:
    def test_flags_frames_whose_extracted_text_is_long_enough(self, fake_brain, video_path) -> None:
        for _ in range(6):
            fake_brain.queue(
                "ocr.provider_extract_text",
                provider_text_result("this is a long enough passage of on-screen text"),
            )

        driver = VideoDetectDocumentsToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["document_frames"]

    def test_does_not_flag_short_text(self, fake_brain, video_path) -> None:
        for _ in range(6):
            fake_brain.queue("ocr.provider_extract_text", provider_text_result("hi"))

        driver = VideoDetectDocumentsToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["document_frames"] == []


class TestVideoDetectSlidesToolDriver:
    def test_never_calls_a_model(self, fake_brain, video_path) -> None:
        driver = VideoDetectSlidesToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert isinstance(response.result["slide_segments"], list)
        # only the one queued filesystem.info Goal was ever issued.
        assert len(fake_brain.requests) == 1


class TestVideoExtractTablesToolDriver:
    def test_flags_tabular_looking_text(self, fake_brain, video_path) -> None:
        tabular_text = "Name   Age   City\nAlice  30    NY\nBob    25    LA"
        for _ in range(6):
            fake_brain.queue("ocr.provider_extract_text", provider_text_result(tabular_text))

        driver = VideoExtractTablesToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["candidates"]
        assert any(candidate["likely_contains_table"] for candidate in response.result["candidates"])


class TestVideoDetectMotionToolDriver:
    def test_reports_motion_events_with_regions(self, fake_brain, video_path) -> None:
        driver = VideoDetectMotionToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["motion_events"]
        assert all("regions" in event for event in response.result["motion_events"])


class TestVideoCompareFramesToolDriver:
    def test_compares_two_frames_of_the_same_video(self, fake_brain, video_path) -> None:
        # this driver validates the path once per frame (two frames -> two Goals).
        fake_brain.queue("filesystem.info", filesystem_info_result(video_path))

        driver = VideoCompareFramesToolDriver(brain=fake_brain)

        response = driver.execute(
            ToolRequest(arguments={"path": video_path, "frame_index_a": 0, "frame_index_b": 30})
        )

        assert 0.0 <= response.result["visual_similarity"] <= 1.0
        assert response.result["overall_difference"] > 0.0


class TestVideoCompareVideosToolDriver:
    def test_compares_two_videos_deterministically(self, fake_brain, video_path) -> None:
        fake_brain.queue("filesystem.info", filesystem_info_result(video_path))

        driver = VideoCompareVideosToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path, "path_b": video_path}))

        assert response.result["same_resolution"] is True
        assert response.result["same_frame_rate"] is True
        assert response.result["visual_similarity"] == 1.0
        assert "semantic_difference" not in response.result

    def test_includes_semantic_difference_when_requested(self, fake_brain, video_path) -> None:
        fake_brain.queue("filesystem.info", filesystem_info_result(video_path))
        fake_brain.queue(
            "vision.provider_compare_images", provider_text_result("both look identical")
        )

        driver = VideoCompareVideosToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(
            ToolRequest(
                arguments={"path": video_path, "path_b": video_path, "include_semantic_diff": True}
            )
        )

        assert response.result["semantic_difference"] == "both look identical"
