"""
PARIKA Video Module - Video Quality Drivers

`video.detect_blur`, `video.detect_black_frames`,
`video.detect_rotation`, `video.detect_corruption`. All four are
100% deterministic (`quality.py`) -- never a model call, per the
task's own explicit instruction for this section.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, frame_io, quality
from .config import VideoToolConfig
from .driver_common import probe_properties, require_path, sample_and_decode, sampling_request_from_arguments
from .exceptions import VideoDecodeError, VideoFrameExtractionError, VideoReadError


class VideoDetectBlurToolDriver:
    """`ToolDriver` implementing `video.detect_blur`."""

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_blur")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        threshold = float(request.arguments.get("threshold", self._config.blur_variance_threshold))

        self._progress.started(message="Sampling frames...")

        sampled = sample_and_decode(
            self._brain,
            path,
            sampling_request_from_arguments(request),
            default_max_frames=self._config.describe_frame_count,
            hard_cap=self._config.max_sample_frames,
        )

        if not sampled.frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Measuring sharpness...")

        entries = []
        for frame in sampled.frames:
            blur = quality.detect_blur(frame.image, threshold=threshold)
            entries.append(
                {
                    "frame_index": frame.index,
                    "timestamp_seconds": frame.timestamp_seconds,
                    "variance": blur.variance,
                    "is_blurry": blur.is_blurry,
                }
            )

        self._progress.completed(message="Completed.")

        blurry_ratio = round(sum(1 for entry in entries if entry["is_blurry"]) / len(entries), 4)

        return ToolResponse(
            result={"frames": entries, "blurry_frame_ratio": blurry_ratio},
            attributes={"path": path},
        )


class VideoDetectBlackFramesToolDriver:
    """`ToolDriver` implementing `video.detect_black_frames`."""

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_black_frames")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        threshold = float(
            request.arguments.get("threshold", self._config.black_frame_brightness_threshold)
        )

        self._progress.started(message="Sampling frames...")

        sampled = sample_and_decode(
            self._brain,
            path,
            sampling_request_from_arguments(request),
            default_max_frames=self._config.max_sample_frames,
            hard_cap=self._config.max_sample_frames,
        )

        if not sampled.frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Measuring brightness...")

        black_frames = []
        for frame in sampled.frames:
            result = quality.detect_black_frame(frame.image, threshold=threshold)
            if result.is_black:
                black_frames.append(
                    {
                        "frame_index": frame.index,
                        "timestamp_seconds": frame.timestamp_seconds,
                        "mean_brightness": result.mean_brightness,
                    }
                )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"black_frames": black_frames, "frames_checked": len(sampled.frames)},
            attributes={"path": path},
        )


class VideoDetectRotationToolDriver:
    """`ToolDriver` implementing `video.detect_rotation`."""

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_rotation")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)

        self._progress.started(message="Sampling frames...")

        sampled = sample_and_decode(
            self._brain,
            path,
            sampling_request_from_arguments(request),
            default_max_frames=min(5, self._config.describe_frame_count),
            hard_cap=self._config.max_sample_frames,
        )

        if not sampled.frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Estimating rotation...")

        votes: dict[int, int] = {}
        confidences: list[float] = []
        for frame in sampled.frames:
            result = quality.detect_rotation(frame.image)
            votes[result.degrees] = votes.get(result.degrees, 0) + 1
            confidences.append(result.confidence)

        best_degrees = max(votes.items(), key=lambda item: item[1])[0]
        average_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "degrees": best_degrees,
                "confidence": average_confidence,
                "frames_checked": len(sampled.frames),
            },
            attributes={"path": path},
        )


class VideoDetectCorruptionToolDriver:
    """
    `ToolDriver` implementing `video.detect_corruption`: attempts to
    open the container and decode a small probe set of frames spread
    across the video, reporting exactly which step failed (container
    open vs individual frame decode) -- never an LLM, per the task's
    own instruction.
    """

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_corruption")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)

        self._progress.started(message="Validating video...")

        try:
            resolved_path = engine.resolve_video_path(self._brain, path)
        except Exception as ex:
            self._progress.failed(message=str(ex))
            return ToolResponse(
                result={"is_corrupted": True, "reason": f"path_validation_failed: {ex}"},
                attributes={"path": path},
            )

        try:
            properties = probe_properties(resolved_path)
        except VideoDecodeError as ex:
            self._progress.completed(message="Completed.")
            return ToolResponse(
                result={"is_corrupted": True, "reason": f"container_open_failed: {ex}"},
                attributes={"path": path},
            )

        self._progress.progress(message="Probing sample frames...")

        from .sampling import uniform_indices

        probe_count = min(5, self._config.describe_frame_count)
        indices = uniform_indices(frame_count=properties.frame_count, max_frames=probe_count)

        undecodable = 0
        for index in indices:
            try:
                frames = frame_io.extract_frames(
                    resolved_path, [index], frame_rate=properties.frame_rate
                )
                if not frames:
                    undecodable += 1
            except (VideoDecodeError, VideoFrameExtractionError):
                undecodable += 1

        self._progress.completed(message="Completed.")

        is_corrupted = undecodable > 0 and undecodable == len(indices)

        return ToolResponse(
            result={
                "is_corrupted": is_corrupted,
                "undecodable_probe_frames": undecodable,
                "probe_frame_count": len(indices),
                "has_video_stream": properties.width is not None,
            },
            attributes={"path": path},
        )
