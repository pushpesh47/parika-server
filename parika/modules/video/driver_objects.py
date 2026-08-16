"""
PARIKA Video Module - Object Understanding Drivers

`video.detect_objects`, `video.count_objects`, `video.track_objects`.
Reuses Vision's own `vision.provider_detect_objects` Provider
Capability directly (`engine.detect_objects_in_frame()`) for semantic
object identification -- never a second object-detection stack --
while `video.count_objects`'s default path and `video.track_objects`'
fallback stay deterministic wherever a classical technique suffices.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, frame_io, motion
from .config import VideoToolConfig
from .driver_common import (
    probe_properties,
    require_path,
    sample_and_decode,
    sampling_request_from_arguments,
)
from .exceptions import VideoReadError
from .sampling import SamplingRequest, dense_indices


def _default_object_instruction() -> str:
    return (
        "Detect and list every distinct object visible in this frame, "
        "with an approximate count for each."
    )


class VideoDetectObjectsToolDriver:
    """
    `ToolDriver` implementing `video.detect_objects`: samples frames
    and reuses `vision.provider_detect_objects` (via
    `engine.detect_objects_in_frame()`) on each one, preserving the
    timestamp of every detection -- temporal information a single-
    image Vision call cannot provide on its own.
    """

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_objects")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        instruction = str(request.arguments.get("instruction", "")).strip() or _default_object_instruction()
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Sampling frames...")

        sampling_request = sampling_request_from_arguments(request)
        sampled = sample_and_decode(
            self._brain,
            path,
            sampling_request,
            default_max_frames=self._config.describe_frame_count,
            hard_cap=self._config.max_sample_frames,
        )

        if not sampled.frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Waiting for Vision model...")

        detections = []
        for frame in sampled.frames:
            image_base64 = frame_io.encode_frame_base64(frame.image)
            text = engine.detect_objects_in_frame(
                self._brain, image_base64, instruction, execution_requirements=execution_requirements
            )
            detections.append(
                {
                    "frame_index": frame.index,
                    "timestamp_seconds": frame.timestamp_seconds,
                    "text": text,
                }
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(result={"detections": detections}, attributes={"path": path})


class VideoCountObjectsToolDriver:
    """
    `ToolDriver` implementing `video.count_objects`. Default path is
    deterministic: per consecutive-frame-pair moving-region counts
    (`motion.detect_motion()`), never a model call. When the caller
    names a `candidate_object`, additionally asks
    `vision.provider_detect_objects` for a per-frame count of that
    specific object -- semantic counting no classical algorithm can
    do reliably. `max_count` is always the *frame-level* maximum,
    never conflated with a unique-object estimate; this Module makes
    no unique-object-count claim (see `video.track_objects`'s own
    docstring for why).
    """

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.count_objects")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        candidate_object = str(request.arguments.get("candidate_object", "")).strip()
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Sampling frames...")

        sampling_request = sampling_request_from_arguments(request)
        sampled = sample_and_decode(
            self._brain,
            path,
            sampling_request,
            default_max_frames=self._config.describe_frame_count,
            hard_cap=self._config.max_sample_frames,
        )

        if not sampled.frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Computing deterministic region counts...")

        per_frame_region_counts = []
        for previous, current in zip(sampled.frames, sampled.frames[1:]):
            result = motion.detect_motion(previous.image, current.image)
            per_frame_region_counts.append(
                {
                    "frame_index": current.index,
                    "timestamp_seconds": current.timestamp_seconds,
                    "moving_region_count": len(result.regions),
                }
            )

        max_moving_region_count = max(
            (entry["moving_region_count"] for entry in per_frame_region_counts), default=0
        )

        result: dict = {
            "per_frame_moving_region_counts": per_frame_region_counts,
            "max_moving_region_count": max_moving_region_count,
            "approximate_unique_object_count": None,
        }

        if candidate_object:
            self._progress.progress(message="Waiting for Vision model...")

            instruction = (
                f"Count only the '{candidate_object}' object(s) visible in "
                "this frame. Respond with just the number, or 0 if none "
                "are visible."
            )
            per_frame_named_counts = []
            for frame in sampled.frames:
                image_base64 = frame_io.encode_frame_base64(frame.image)
                text = engine.detect_objects_in_frame(
                    self._brain, image_base64, instruction, execution_requirements=execution_requirements
                ).strip()
                per_frame_named_counts.append(
                    {
                        "frame_index": frame.index,
                        "timestamp_seconds": frame.timestamp_seconds,
                        "count_text": text,
                    }
                )

            result["candidate_object"] = candidate_object
            result["per_frame_named_counts"] = per_frame_named_counts

        self._progress.completed(message="Completed.")

        return ToolResponse(result=result, attributes={"path": path})


def _legacy_tracker_available() -> bool:
    try:
        import cv2

        return hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerKCF_create")
    except ImportError:
        return False


class VideoTrackObjectsToolDriver:
    """
    `ToolDriver` implementing `video.track_objects`. `opencv-python-
    headless` (the `video`/`vision` extras' dependency) ships without
    the legacy contrib tracking API this v1 would otherwise use, so
    this Capability honestly falls back to densely-sampled, per-frame
    object detection (`vision.provider_detect_objects`, via
    `engine.detect_objects_in_frame()`) with `tracking_available:
    False` and no identity linking across frames -- exactly the task's
    own "fall back to frame-level detection rather than inventing
    unreliable identity tracking" instruction, applied literally.
    """

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.track_objects")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        instruction = str(request.arguments.get("instruction", "")).strip() or _default_object_instruction()
        execution_requirements = request.metadata.get("execution_requirements")
        tracking_available = _legacy_tracker_available()

        self._progress.started(message="Densely sampling frames...")

        resolved_path = engine.resolve_video_path(self._brain, path)
        properties = probe_properties(resolved_path)
        indices = dense_indices(
            frame_count=properties.frame_count,
            frame_rate=properties.frame_rate,
            target_fps=self._config.dense_sample_target_fps,
            max_frames=self._config.max_sample_frames,
        )
        frames = frame_io.extract_frames(resolved_path, indices, frame_rate=properties.frame_rate)

        if not frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Waiting for Vision model...")

        detections = []
        for frame in frames:
            image_base64 = frame_io.encode_frame_base64(frame.image)
            text = engine.detect_objects_in_frame(
                self._brain, image_base64, instruction, execution_requirements=execution_requirements
            )
            detections.append(
                {
                    "frame_index": frame.index,
                    "timestamp_seconds": frame.timestamp_seconds,
                    "text": text,
                }
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"tracking_available": tracking_available, "detections": detections},
            attributes={"path": path},
        )
