"""
Unit tests for the Video Module's deterministic quality
(`video.detect_blur`, `video.detect_black_frames`,
`video.detect_rotation`, `video.detect_corruption`) and timeline
(`video.detect_scene_changes`, `video.detect_shots`,
`video.segment_video`) ToolDrivers, against the real synthetic video
fixture -- never a real Brain/Provider.
"""

from __future__ import annotations

import pytest

pytest.importorskip("cv2")

from parika.core.tool_manager.request import ToolRequest
from parika.modules.video.config import VideoToolConfig
from parika.modules.video.driver_quality import (
    VideoDetectBlackFramesToolDriver,
    VideoDetectBlurToolDriver,
    VideoDetectCorruptionToolDriver,
    VideoDetectRotationToolDriver,
)
from parika.modules.video.driver_timeline import (
    VideoDetectSceneChangesToolDriver,
    VideoDetectShotsToolDriver,
    VideoSegmentToolDriver,
)


class TestVideoDetectBlackFramesToolDriver:
    def test_flags_black_frames_in_first_half(self, fake_brain, video_path) -> None:
        driver = VideoDetectBlackFramesToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["black_frames"]
        assert all(
            frame["timestamp_seconds"] < 2.5 for frame in response.result["black_frames"]
        )


class TestVideoDetectBlurToolDriver:
    def test_returns_per_frame_sharpness(self, fake_brain, video_path) -> None:
        driver = VideoDetectBlurToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["frames"]
        assert 0.0 <= response.result["blurry_frame_ratio"] <= 1.0


class TestVideoDetectRotationToolDriver:
    def test_returns_a_confident_degree_estimate(self, fake_brain, video_path) -> None:
        driver = VideoDetectRotationToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["degrees"] in (0, 90, 180, 270)


class TestVideoDetectCorruptionToolDriver:
    def test_valid_video_is_not_corrupted(self, fake_brain, video_path) -> None:
        driver = VideoDetectCorruptionToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["is_corrupted"] is False

    def test_empty_file_is_reported_as_corrupted(self, fake_brain, tmp_path) -> None:
        empty_path = tmp_path / "empty.mp4"
        empty_path.write_bytes(b"")

        from .conftest import filesystem_info_result

        fake_brain._queues["filesystem.info"] = [filesystem_info_result(str(empty_path))]  # noqa: SLF001

        driver = VideoDetectCorruptionToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": str(empty_path)}))

        assert response.result["is_corrupted"] is True


class TestVideoDetectSceneChangesToolDriver:
    def test_detects_the_hard_color_transition(self, fake_brain, video_path) -> None:
        driver = VideoDetectSceneChangesToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["scene_changes"]
        assert any(2.0 <= change["timestamp_seconds"] <= 3.0 for change in response.result["scene_changes"])


class TestVideoDetectShotsToolDriver:
    def test_detects_at_least_one_shot_boundary(self, fake_brain, video_path) -> None:
        driver = VideoDetectShotsToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["shots"]


class TestVideoSegmentToolDriver:
    def test_splits_into_two_segments(self, fake_brain, video_path) -> None:
        driver = VideoSegmentToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        segments = response.result["segments"]
        assert len(segments) >= 2
        assert segments[0]["start_seconds"] == 0.0
        assert segments[-1]["end_seconds"] >= 4.0
