"""
Unit tests for the Video Module's I/O ToolDrivers
(`video.read_video`, `video.extract_metadata`, `video.extract_frames`,
`video.extract_keyframes`, `video.extract_thumbnails`), against a
real, small synthetic video file -- never a real Brain/Provider.
"""

from __future__ import annotations

import pytest

pytest.importorskip("cv2")

from parika.core.tool_manager.request import ToolRequest
from parika.modules.video.config import VideoToolConfig
from parika.modules.video.driver_io import (
    VideoFrameExtractionToolDriver,
    VideoKeyframeToolDriver,
    VideoMetadataToolDriver,
    VideoReadToolDriver,
    VideoThumbnailToolDriver,
)
from parika.modules.video.exceptions import VideoReadError

from .conftest import failed_result


class _FakeToolManager:
    """A `ToolManager` stand-in whose `execute()` always fails -- simulates `ffprobe`/Shell Tool being unavailable."""

    def execute(self, tool_id, request):  # noqa: ANN001
        raise RuntimeError("shell tool unavailable in this test")


class TestVideoReadToolDriver:
    def test_reports_basic_properties(self, fake_brain, video_path) -> None:
        driver = VideoReadToolDriver(brain=fake_brain)

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["readable"] is True
        assert response.result["width"] == 64
        assert response.result["height"] == 64
        assert response.result["frame_count"] == 50
        assert response.result["container_format"] == "mp4"

    def test_requires_non_empty_path(self, fake_brain) -> None:
        driver = VideoReadToolDriver(brain=fake_brain)

        with pytest.raises(VideoReadError):
            driver.execute(ToolRequest(arguments={"path": ""}))

    def test_propagates_filesystem_validation_failure(self, fake_brain) -> None:
        fake_brain._queues["filesystem.info"] = [failed_result("path does not exist")]  # noqa: SLF001

        driver = VideoReadToolDriver(brain=fake_brain)

        with pytest.raises(VideoReadError):
            driver.execute(ToolRequest(arguments={"path": "/does/not/exist.mp4"}))


class TestVideoMetadataToolDriver:
    def test_extracts_deterministic_metadata(self, fake_brain, video_path) -> None:
        driver = VideoMetadataToolDriver(brain=fake_brain, tool_manager=_FakeToolManager())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["width"] == 64
        assert response.result["height"] == 64
        assert response.result["frame_rate"] == 10.0
        assert response.result["frame_count"] == 50
        assert response.result["duration_seconds"] == 5.0
        assert response.result["container_format"] == "mp4"
        # ffprobe unavailable in this test -> bitrate/audio stream stay None.
        assert response.result["bitrate"] is None
        assert response.result["has_audio_stream"] is None


class TestVideoFrameExtractionToolDriver:
    def test_extracts_bounded_default_sample(self, fake_brain, video_path) -> None:
        driver = VideoFrameExtractionToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path, "max_frames": 5}))

        assert response.result["frame_count_returned"] <= 5
        assert all("image_base64" not in frame for frame in response.result["frames"])

    def test_include_image_data_returns_base64(self, fake_brain, video_path) -> None:
        driver = VideoFrameExtractionToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(
            ToolRequest(arguments={"path": video_path, "max_frames": 2, "include_image_data": True})
        )

        assert all(frame["image_base64"] for frame in response.result["frames"])

    def test_explicit_frame_indices_are_honored(self, fake_brain, video_path) -> None:
        driver = VideoFrameExtractionToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(
            ToolRequest(arguments={"path": video_path, "frame_indices": [0, 10, 20]})
        )

        returned_indices = {frame["frame_index"] for frame in response.result["frames"]}
        assert returned_indices == {0, 10, 20}


class TestVideoKeyframeToolDriver:
    def test_selects_at_least_one_keyframe_per_detected_shot(self, fake_brain, video_path) -> None:
        driver = VideoKeyframeToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        # the fixture video has one hard color transition -> at least 2 shots.
        assert response.result["keyframe_count"] >= 2


class TestVideoThumbnailToolDriver:
    def test_builds_a_contact_sheet(self, fake_brain, video_path) -> None:
        driver = VideoThumbnailToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(
            ToolRequest(arguments={"path": video_path, "columns": 2, "rows": 2})
        )

        assert response.result["image_base64"]
        assert response.result["image_format"] == "JPEG"
        assert len(response.result["frames"]) == 4
