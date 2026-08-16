"""
Unit tests for the Video Module's Provider-backed understanding
(`video.describe_video`, `video.answer_question`,
`video.classify_video`) and object-reuse
(`video.detect_objects`, `video.count_objects`, `video.track_objects`,
`video.extract_text`) ToolDrivers, using a `FakeBrain` for every
nested Provider Goal -- never a real Provider.
"""

from __future__ import annotations

import pytest

pytest.importorskip("cv2")

from parika.core.tool_manager.request import ToolRequest
from parika.modules.video.config import VideoToolConfig
from parika.modules.video.driver_objects import (
    VideoCountObjectsToolDriver,
    VideoDetectObjectsToolDriver,
    VideoTrackObjectsToolDriver,
)
from parika.modules.video.driver_text import VideoExtractTextToolDriver
from parika.modules.video.driver_understanding import (
    VideoClassifyToolDriver,
    VideoUnderstandingSpec,
    VideoUnderstandingToolDriver,
)
from parika.modules.video.exceptions import VideoAnalysisError

from .conftest import failed_result, provider_text_result


def _queue_provider(fake_brain, capability_id: str, text: str, times: int = 1) -> None:
    for _ in range(times):
        fake_brain.queue(capability_id, provider_text_result(text))


class TestVideoUnderstandingToolDriver:
    def test_describe_video_returns_provider_text(self, fake_brain, video_path) -> None:
        _queue_provider(fake_brain, "video.provider_describe_video", "a video of colors")

        spec = VideoUnderstandingSpec(
            provider_capability_id="video.provider_describe_video",
            default_instruction="Describe this video.",
            frame_count_attribute="describe_frame_count",
        )
        driver = VideoUnderstandingToolDriver(brain=fake_brain, spec=spec, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["text"] == "a video of colors"
        assert response.result["frames_analyzed"]

    def test_answer_question_requires_question_argument(self, fake_brain, video_path) -> None:
        spec = VideoUnderstandingSpec(
            provider_capability_id="video.provider_answer_question",
            default_instruction="",
            question_argument=True,
            frame_count_attribute="answer_question_frame_count",
        )
        driver = VideoUnderstandingToolDriver(brain=fake_brain, spec=spec, config=VideoToolConfig())

        with pytest.raises(Exception):
            driver.execute(ToolRequest(arguments={"path": video_path}))

    def test_answer_question_with_ocr_included(self, fake_brain, video_path) -> None:
        spec = VideoUnderstandingSpec(
            provider_capability_id="video.provider_answer_question",
            default_instruction="",
            question_argument=True,
            frame_count_attribute="answer_question_frame_count",
        )
        driver = VideoUnderstandingToolDriver(brain=fake_brain, spec=spec, config=VideoToolConfig())

        # include_ocr triggers one ocr.provider_extract_text Goal per frame.
        fake_brain.queue("ocr.provider_extract_text", provider_text_result(""))
        for _ in range(6):
            fake_brain.queue("ocr.provider_extract_text", provider_text_result(""))
        _queue_provider(fake_brain, "video.provider_answer_question", "green")

        response = driver.execute(
            ToolRequest(
                arguments={"path": video_path, "question": "What color is it?", "include_ocr": True}
            )
        )

        assert response.result["text"] == "green"

    def test_raises_video_analysis_error_when_provider_fails(self, fake_brain, video_path) -> None:
        fake_brain.queue("video.provider_describe_video", failed_result("no provider available"))

        spec = VideoUnderstandingSpec(
            provider_capability_id="video.provider_describe_video",
            default_instruction="Describe this video.",
            frame_count_attribute="describe_frame_count",
        )
        driver = VideoUnderstandingToolDriver(brain=fake_brain, spec=spec, config=VideoToolConfig())

        with pytest.raises(VideoAnalysisError):
            driver.execute(ToolRequest(arguments={"path": video_path}))


class TestVideoClassifyToolDriver:
    def test_deterministic_category_without_candidate_labels(self, fake_brain, video_path) -> None:
        driver = VideoClassifyToolDriver(
            brain=fake_brain, provider_capability_id="video.provider_classify_video", config=VideoToolConfig()
        )

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["deterministic_category"] in (
            "static_or_slideshow",
            "moderate_activity",
            "dynamic_high_activity",
        )
        assert "semantic_label" not in response.result

    def test_calls_provider_only_when_candidate_labels_supplied(self, fake_brain, video_path) -> None:
        _queue_provider(fake_brain, "video.provider_classify_video", "nature")

        driver = VideoClassifyToolDriver(
            brain=fake_brain, provider_capability_id="video.provider_classify_video", config=VideoToolConfig()
        )

        response = driver.execute(
            ToolRequest(arguments={"path": video_path, "candidate_labels": ["sports", "nature"]})
        )

        assert response.result["semantic_label"] == "nature"


class TestVideoDetectObjectsToolDriver:
    def test_returns_one_detection_per_sampled_frame(self, fake_brain, video_path) -> None:
        for _ in range(3):
            fake_brain.queue("vision.provider_detect_objects", provider_text_result("a square"))

        driver = VideoDetectObjectsToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path, "max_frames": 3}))

        assert len(response.result["detections"]) == 3
        assert all(detection["text"] == "a square" for detection in response.result["detections"])


class TestVideoCountObjectsToolDriver:
    def test_deterministic_counts_require_no_provider_call(self, fake_brain, video_path) -> None:
        driver = VideoCountObjectsToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path, "max_frames": 4}))

        assert response.result["approximate_unique_object_count"] is None
        assert response.result["max_moving_region_count"] >= 0
        assert "candidate_object" not in response.result

    def test_named_object_escalates_to_provider(self, fake_brain, video_path) -> None:
        for _ in range(3):
            fake_brain.queue("vision.provider_detect_objects", provider_text_result("1"))

        driver = VideoCountObjectsToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(
            ToolRequest(arguments={"path": video_path, "candidate_object": "square", "max_frames": 3})
        )

        assert response.result["candidate_object"] == "square"
        assert len(response.result["per_frame_named_counts"]) == 3


class TestVideoTrackObjectsToolDriver:
    def test_falls_back_to_frame_level_detection(self, fake_brain, video_path) -> None:
        for _ in range(10):
            fake_brain.queue("vision.provider_detect_objects", provider_text_result("a square"))

        driver = VideoTrackObjectsToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        assert response.result["tracking_available"] is False
        assert response.result["detections"]


class TestVideoExtractTextToolDriver:
    def test_deduplicates_repeated_text_segments(self, fake_brain, video_path) -> None:
        # every sampled frame is visually distinct enough (moving square)
        # to avoid the near-identical-frame skip, so queue one OCR result
        # per interval-sampled frame.
        for _ in range(6):
            fake_brain.queue("ocr.provider_extract_text", provider_text_result("HELLO"))

        driver = VideoExtractTextToolDriver(brain=fake_brain, config=VideoToolConfig())

        response = driver.execute(ToolRequest(arguments={"path": video_path}))

        segments = response.result["text_segments"]
        assert len(segments) == 1
        assert segments[0]["text"] == "HELLO"
