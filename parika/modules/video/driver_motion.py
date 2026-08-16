"""
PARIKA Video Module - Motion Analysis Drivers

`video.detect_motion` and `video.compare_frames`. Both purely
deterministic frame-differencing (`motion.py`/`hashing.py`) -- never
a model call, per the task's own "prefer deterministic computer-
vision techniques" instruction for this section.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, frame_io, hashing, motion
from .config import VideoToolConfig
from .driver_common import probe_properties, require_path, sampling_request_from_arguments
from .exceptions import VideoReadError
from .sampling import dense_indices, resolve_indices


class VideoDetectMotionToolDriver:
    """
    `ToolDriver` implementing `video.detect_motion`: dense-samples
    the video and computes `motion.detect_motion()` between every
    consecutive pair, returning per-transition changed-pixel ratios
    and candidate motion regions.
    """

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_motion")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        pixel_threshold = int(request.arguments.get("pixel_threshold", self._config.motion_pixel_threshold))
        area_ratio_threshold = float(
            request.arguments.get("area_ratio_threshold", self._config.motion_area_ratio_threshold)
        )

        self._progress.started(message="Sampling frames...")

        resolved_path = engine.resolve_video_path(self._brain, path)
        properties = probe_properties(resolved_path)
        sampling_request = sampling_request_from_arguments(request)

        if sampling_request.frame_indices or sampling_request.timestamps_seconds or sampling_request.interval_seconds:
            indices = resolve_indices(
                sampling_request,
                frame_count=properties.frame_count,
                frame_rate=properties.frame_rate,
                default_max_frames=self._config.max_sample_frames,
                hard_cap=self._config.max_sample_frames,
            )
        else:
            indices = dense_indices(
                frame_count=properties.frame_count,
                frame_rate=properties.frame_rate,
                target_fps=self._config.dense_sample_target_fps,
                max_frames=self._config.max_sample_frames,
            )

        frames = frame_io.extract_frames(resolved_path, indices, frame_rate=properties.frame_rate)

        if len(frames) < 2:
            self._progress.completed(message="Completed.")
            return ToolResponse(result={"motion_events": []}, attributes={"path": path})

        self._progress.progress(message="Comparing consecutive frames...")

        events = []
        for previous, current in zip(frames, frames[1:]):
            motion_result = motion.detect_motion(
                previous.image,
                current.image,
                pixel_threshold=pixel_threshold,
                area_ratio_threshold=area_ratio_threshold,
            )
            events.append(
                {
                    "frame_index": current.index,
                    "timestamp_seconds": current.timestamp_seconds,
                    "changed_pixel_ratio": motion_result.changed_pixel_ratio,
                    "has_motion": motion_result.has_motion,
                    "region_count": len(motion_result.regions),
                    "regions": [box.to_result_dict() for box in motion_result.regions],
                }
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(result={"motion_events": events}, attributes={"path": path})


class VideoCompareFramesToolDriver:
    """
    `ToolDriver` implementing `video.compare_frames`: compares two
    frames, either from the same video (`timestamp_a`/`timestamp_b`
    or `frame_index_a`/`frame_index_b` on `path`) or from two
    different videos (`path` and `path_b`), via `hashing.change_score()`
    (visual/structural similarity) and `hashing.find_diff_regions()`
    (changed regions) -- the same deterministic techniques
    `video.detect_scene_changes`/`video.detect_motion` already use.
    """

    def __init__(self, *, brain: Brain, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._progress = progress_reporter or NullProgressReporter("video.compare_frames")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path_a = require_path(request)
        path_b = str(request.arguments.get("path_b", "")).strip() or path_a

        self._progress.started(message="Resolving frames...")

        frame_a = self._decode_one(
            path_a,
            frame_index=request.arguments.get("frame_index_a"),
            timestamp=request.arguments.get("timestamp_a"),
        )
        frame_b = self._decode_one(
            path_b,
            frame_index=request.arguments.get("frame_index_b"),
            timestamp=request.arguments.get("timestamp_b"),
        )

        self._progress.progress(message="Comparing frames...")

        score = hashing.change_score(frame_a.image, frame_b.image)
        diff_regions = hashing.find_diff_regions(frame_a.image, frame_b.image)

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "visual_similarity": round(1.0 - score.pixel_dissimilarity, 4),
                "structural_similarity": round(1.0 - score.hash_distance_ratio, 4),
                "overall_difference": score.overall,
                "changed_region_count": len(diff_regions),
                "changed_regions": [box.to_result_dict() for box in diff_regions],
            },
            attributes={
                "path_a": path_a,
                "path_b": path_b,
                "frame_a": {"frame_index": frame_a.index, "timestamp_seconds": frame_a.timestamp_seconds},
                "frame_b": {"frame_index": frame_b.index, "timestamp_seconds": frame_b.timestamp_seconds},
            },
        )

    def _decode_one(self, path: str, *, frame_index: object, timestamp: object):
        resolved_path = engine.resolve_video_path(self._brain, path)
        properties = probe_properties(resolved_path)

        if frame_index is not None:
            index = int(frame_index)
        elif timestamp is not None:
            rate = properties.frame_rate or 25.0
            index = max(0, round(float(timestamp) * rate))
        else:
            index = 0

        frames = frame_io.extract_frames(resolved_path, [index], frame_rate=properties.frame_rate)

        if not frames:
            raise VideoReadError(f"Could not decode frame {index} from '{path}'.")

        return frames[0]
