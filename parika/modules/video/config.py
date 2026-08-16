"""
PARIKA Video Module - Configuration

Reads the `[video]` configuration section and detects, at runtime,
whether the optional `opencv-python-headless` dependency (frame
decoding via `cv2.VideoCapture`, the same library backing the Vision
Module's own `vision` extra) is installed. Mirrors exactly the
pattern `parika/modules/vision/config.py` already establishes.

Every capability that only needs the base `pillow`/`numpy`
dependencies (already required by `pyproject.toml`) degrades to a
clear `VideoDependencyUnavailableError` rather than a crash when
`opencv-python-headless` is missing, since decoding compressed video
containers (mp4/mkv/avi/webm/...) genuinely requires it -- there is
no pure-Pillow fallback for video demuxing/decoding.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

from parika.core.configuration.configuration import Configuration

from .exceptions import VideoDependencyUnavailableError

DEFAULT_ENABLED = True

# Frame sampling defaults (see `sampling.py`'s adaptive dispatcher).
DEFAULT_MAX_SAMPLE_FRAMES = 64
DEFAULT_DESCRIBE_FRAME_COUNT = 6
DEFAULT_SUMMARIZE_FRAME_COUNT = 10
DEFAULT_ANSWER_QUESTION_FRAME_COUNT = 6
DEFAULT_CLASSIFY_FRAME_COUNT = 4
DEFAULT_DENSE_SAMPLE_TARGET_FPS = 2.0
DEFAULT_FOCUS_WINDOW_SECONDS = 6.0

# Deterministic thresholds.
DEFAULT_SCENE_CHANGE_THRESHOLD = 0.35
"""Normalized perceptual-hash-distance + histogram-delta blend above
which two consecutive sampled frames are considered a shot boundary."""

DEFAULT_BLUR_VARIANCE_THRESHOLD = 100.0
DEFAULT_BLACK_FRAME_BRIGHTNESS_THRESHOLD = 16.0
DEFAULT_MOTION_PIXEL_THRESHOLD = 25
DEFAULT_MOTION_AREA_RATIO_THRESHOLD = 0.01
DEFAULT_MIN_SLIDE_DURATION_SECONDS = 2.0
DEFAULT_THUMBNAIL_COLUMNS = 4
DEFAULT_THUMBNAIL_ROWS = 4
DEFAULT_THUMBNAIL_CELL_WIDTH = 240


def opencv_dependency_available() -> bool:
    """
    Whether the optional `opencv-python-headless` dependency (frame
    decoding via `cv2.VideoCapture`) is installed.
    """

    return importlib.util.find_spec("cv2") is not None


def require_opencv() -> None:
    """
    Raise `VideoDependencyUnavailableError` unless the optional
    `opencv-python-headless` dependency is installed. Shared by every
    Capability in this Module that needs to decode a video container.
    """

    if not opencv_dependency_available():
        raise VideoDependencyUnavailableError(
            "This Video feature requires the optional 'video' "
            "dependency group (opencv-python-headless) to be "
            "installed."
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class VideoToolConfig:
    """
    Immutable, typed snapshot of `[video]` configuration.
    """

    enabled: bool = DEFAULT_ENABLED
    max_sample_frames: int = DEFAULT_MAX_SAMPLE_FRAMES
    describe_frame_count: int = DEFAULT_DESCRIBE_FRAME_COUNT
    summarize_frame_count: int = DEFAULT_SUMMARIZE_FRAME_COUNT
    answer_question_frame_count: int = DEFAULT_ANSWER_QUESTION_FRAME_COUNT
    classify_frame_count: int = DEFAULT_CLASSIFY_FRAME_COUNT
    dense_sample_target_fps: float = DEFAULT_DENSE_SAMPLE_TARGET_FPS
    focus_window_seconds: float = DEFAULT_FOCUS_WINDOW_SECONDS
    scene_change_threshold: float = DEFAULT_SCENE_CHANGE_THRESHOLD
    blur_variance_threshold: float = DEFAULT_BLUR_VARIANCE_THRESHOLD
    black_frame_brightness_threshold: float = DEFAULT_BLACK_FRAME_BRIGHTNESS_THRESHOLD
    motion_pixel_threshold: int = DEFAULT_MOTION_PIXEL_THRESHOLD
    motion_area_ratio_threshold: float = DEFAULT_MOTION_AREA_RATIO_THRESHOLD
    min_slide_duration_seconds: float = DEFAULT_MIN_SLIDE_DURATION_SECONDS
    thumbnail_columns: int = DEFAULT_THUMBNAIL_COLUMNS
    thumbnail_rows: int = DEFAULT_THUMBNAIL_ROWS
    thumbnail_cell_width: int = DEFAULT_THUMBNAIL_CELL_WIDTH

    @property
    def decode_available(self) -> bool:
        """Whether frame decoding (`cv2.VideoCapture`) is installed."""

        return opencv_dependency_available()


def load_video_config(configuration: Configuration | None) -> VideoToolConfig:
    """
    Build a `VideoToolConfig` snapshot from `Configuration`.
    """

    if configuration is None:
        return VideoToolConfig()

    return VideoToolConfig(
        enabled=bool(configuration.get("video.enabled", DEFAULT_ENABLED)),
        max_sample_frames=int(
            configuration.get("video.max_sample_frames", DEFAULT_MAX_SAMPLE_FRAMES)
        ),
        describe_frame_count=int(
            configuration.get(
                "video.describe_frame_count", DEFAULT_DESCRIBE_FRAME_COUNT
            )
        ),
        summarize_frame_count=int(
            configuration.get(
                "video.summarize_frame_count", DEFAULT_SUMMARIZE_FRAME_COUNT
            )
        ),
        answer_question_frame_count=int(
            configuration.get(
                "video.answer_question_frame_count",
                DEFAULT_ANSWER_QUESTION_FRAME_COUNT,
            )
        ),
        classify_frame_count=int(
            configuration.get(
                "video.classify_frame_count", DEFAULT_CLASSIFY_FRAME_COUNT
            )
        ),
        dense_sample_target_fps=float(
            configuration.get(
                "video.dense_sample_target_fps", DEFAULT_DENSE_SAMPLE_TARGET_FPS
            )
        ),
        focus_window_seconds=float(
            configuration.get(
                "video.focus_window_seconds", DEFAULT_FOCUS_WINDOW_SECONDS
            )
        ),
        scene_change_threshold=float(
            configuration.get(
                "video.scene_change_threshold", DEFAULT_SCENE_CHANGE_THRESHOLD
            )
        ),
        blur_variance_threshold=float(
            configuration.get(
                "video.blur_variance_threshold", DEFAULT_BLUR_VARIANCE_THRESHOLD
            )
        ),
        black_frame_brightness_threshold=float(
            configuration.get(
                "video.black_frame_brightness_threshold",
                DEFAULT_BLACK_FRAME_BRIGHTNESS_THRESHOLD,
            )
        ),
        motion_pixel_threshold=int(
            configuration.get(
                "video.motion_pixel_threshold", DEFAULT_MOTION_PIXEL_THRESHOLD
            )
        ),
        motion_area_ratio_threshold=float(
            configuration.get(
                "video.motion_area_ratio_threshold",
                DEFAULT_MOTION_AREA_RATIO_THRESHOLD,
            )
        ),
        min_slide_duration_seconds=float(
            configuration.get(
                "video.min_slide_duration_seconds",
                DEFAULT_MIN_SLIDE_DURATION_SECONDS,
            )
        ),
        thumbnail_columns=int(
            configuration.get("video.thumbnail_columns", DEFAULT_THUMBNAIL_COLUMNS)
        ),
        thumbnail_rows=int(
            configuration.get("video.thumbnail_rows", DEFAULT_THUMBNAIL_ROWS)
        ),
        thumbnail_cell_width=int(
            configuration.get(
                "video.thumbnail_cell_width", DEFAULT_THUMBNAIL_CELL_WIDTH
            )
        ),
    )
