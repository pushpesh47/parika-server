"""
PARIKA Video Module - Timeline Understanding Drivers

`video.generate_timeline`, `video.detect_scene_changes`,
`video.detect_shots`, `video.segment_video`, and
`video.detect_key_moments`. Temporal understanding -- the primary
distinction between this Module and Vision -- lives here.
`detect_scene_changes`/`detect_shots`/`segment_video` are 100%
deterministic (`scene_detection.py`, itself built on `hashing.py`);
only `generate_timeline` (optionally) and `detect_key_moments`
(optionally) escalate to a Provider Capability, and only for the
handful of already-selected keyframes/candidates -- never every
sampled frame.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, frame_io, keyframes, scene_detection
from .config import VideoToolConfig
from .driver_common import probe_properties, require_path
from .exceptions import VideoReadError
from .sampling import dense_indices
from .video_model import TimelineEntry

_DEFAULT_MAX_TIMELINE_ENTRIES = 12
_DEFAULT_MAX_KEY_MOMENTS = 5


def _sample_dense(brain: Brain, path: str, config: VideoToolConfig, *, target_fps: float | None = None):
    resolved_path = engine.resolve_video_path(brain, path)
    properties = probe_properties(resolved_path)

    indices = dense_indices(
        frame_count=properties.frame_count,
        frame_rate=properties.frame_rate,
        target_fps=target_fps or config.dense_sample_target_fps,
        max_frames=config.max_sample_frames,
    )
    frames = frame_io.extract_frames(resolved_path, indices, frame_rate=properties.frame_rate)

    return resolved_path, properties, frames


class VideoDetectSceneChangesToolDriver:
    """`ToolDriver` implementing `video.detect_scene_changes`. Deterministic only."""

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_scene_changes")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        threshold = float(request.arguments.get("threshold", self._config.scene_change_threshold))

        self._progress.started(message="Sampling frames...")
        _, _, frames = _sample_dense(self._brain, path, self._config)

        if len(frames) < 2:
            self._progress.completed(message="Completed.")
            return ToolResponse(result={"scene_changes": []}, attributes={"path": path})

        self._progress.progress(message="Comparing consecutive frames...")
        boundaries = scene_detection.detect_boundaries(frames, threshold=threshold)
        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"scene_changes": [boundary.to_result_dict() for boundary in boundaries]},
            attributes={"path": path},
        )


class VideoDetectShotsToolDriver:
    """
    `ToolDriver` implementing `video.detect_shots`: the same
    deterministic frame-comparison detector as `video.detect_scene_changes`,
    sampled more densely (finer temporal granularity is what
    distinguishes a "shot" boundary from a coarser "scene change" in
    this v1 -- see `scene_detection.py`'s own docstring).
    """

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_shots")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        threshold = float(request.arguments.get("threshold", self._config.scene_change_threshold))

        self._progress.started(message="Densely sampling frames...")
        _, _, frames = _sample_dense(
            self._brain, path, self._config, target_fps=self._config.dense_sample_target_fps * 2
        )

        if len(frames) < 2:
            self._progress.completed(message="Completed.")
            return ToolResponse(result={"shots": []}, attributes={"path": path})

        self._progress.progress(message="Comparing consecutive frames...")
        boundaries = scene_detection.detect_boundaries(frames, threshold=threshold)
        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"shots": [boundary.to_result_dict() for boundary in boundaries]},
            attributes={"path": path},
        )


class VideoSegmentToolDriver:
    """`ToolDriver` implementing `video.segment_video`. Deterministic only."""

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.segment_video")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        threshold = float(request.arguments.get("threshold", self._config.scene_change_threshold))

        self._progress.started(message="Sampling frames...")
        _, _, frames = _sample_dense(self._brain, path, self._config)

        if not frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Detecting shot boundaries...")
        boundaries = scene_detection.detect_boundaries(frames, threshold=threshold)
        segments = scene_detection.segments_from_boundaries(
            boundaries,
            first_frame_index=frames[0].index,
            first_timestamp_seconds=frames[0].timestamp_seconds,
            last_frame_index=frames[-1].index,
            last_timestamp_seconds=frames[-1].timestamp_seconds,
        )
        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"segments": [segment.to_result_dict() for segment in segments]},
            attributes={"path": path},
        )


class VideoGenerateTimelineToolDriver:
    """
    `ToolDriver` implementing `video.generate_timeline`: builds one
    `TimelineEntry` per detected keyframe (reusing the exact same
    shot-boundary/keyframe-selection algorithms as
    `video.extract_keyframes`), optionally narrating each keyframe via
    `engine.describe_frame()`/`engine.extract_text_from_frame()` when
    `include_descriptions`/`include_text` are set -- bounded to the
    already-small keyframe set, never every sampled frame.
    """

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.generate_timeline")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        include_descriptions = bool(request.arguments.get("include_descriptions", True))
        include_text = bool(request.arguments.get("include_text", False))
        max_entries = int(request.arguments.get("max_entries", _DEFAULT_MAX_TIMELINE_ENTRIES))
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Sampling frames...")
        resolved_path, properties, frames = _sample_dense(self._brain, path, self._config)

        if not frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Detecting shot boundaries...")
        boundaries = scene_detection.detect_boundaries(
            frames, threshold=self._config.scene_change_threshold
        )
        boundary_indices = {boundary.frame_index for boundary in boundaries}

        if len(frames) <= 1:
            keyframe_indices = [frame.index for frame in frames]
        else:
            segments = scene_detection.segments_from_boundaries(
                boundaries,
                first_frame_index=frames[0].index,
                first_timestamp_seconds=frames[0].timestamp_seconds,
                last_frame_index=frames[-1].index,
                last_timestamp_seconds=frames[-1].timestamp_seconds,
            )
            keyframe_indices = keyframes.keyframe_indices_from_segments(
                segments, frame_rate=properties.frame_rate or 25.0, max_keyframes=max_entries
            )

        by_index = {frame.index: frame for frame in frames}
        missing = [index for index in keyframe_indices if index not in by_index]
        if missing:
            for frame in frame_io.extract_frames(
                resolved_path, missing, frame_rate=properties.frame_rate
            ):
                by_index[frame.index] = frame

        entries: list[TimelineEntry] = []

        self._progress.progress(message="Building timeline entries...")

        for index in keyframe_indices:
            frame = by_index.get(index)
            if frame is None:
                continue

            observations = ""
            visible_text = ""

            if include_descriptions:
                image_base64 = frame_io.encode_frame_base64(frame.image)
                observations = engine.describe_frame(
                    self._brain,
                    image_base64,
                    "In one short sentence, describe what is happening in this frame.",
                    execution_requirements=execution_requirements,
                ).strip()

            if include_text:
                image_base64 = frame_io.encode_frame_base64(frame.image)
                visible_text = engine.extract_text_from_frame(
                    self._brain, image_base64, execution_requirements=execution_requirements
                ).strip()

            entries.append(
                TimelineEntry(
                    timestamp_seconds=frame.timestamp_seconds,
                    frame_index=frame.index,
                    is_scene_change=frame.index in boundary_indices,
                    observations=observations,
                    visible_text=visible_text,
                )
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"timeline": [entry.to_result_dict() for entry in entries]},
            attributes={"path": path},
        )


class VideoDetectKeyMomentsToolDriver:
    """
    `ToolDriver` implementing `video.detect_key_moments`: ranks
    deterministic shot-boundary change scores to obtain candidate
    moments (zero model calls), then optionally asks the
    `video.provider_detect_key_moments` Capability to explain/refine
    the top candidates when `include_explanation` is set -- bounded
    to `max_moments`, never every sampled frame.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        provider_capability_id: str,
        config: VideoToolConfig,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._provider_capability_id = provider_capability_id
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_key_moments")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        max_moments = int(request.arguments.get("max_moments", _DEFAULT_MAX_KEY_MOMENTS))
        include_explanation = bool(request.arguments.get("include_explanation", False))
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Sampling frames...")
        _, _, frames = _sample_dense(self._brain, path, self._config)

        if len(frames) < 2:
            self._progress.completed(message="Completed.")
            return ToolResponse(result={"key_moments": []}, attributes={"path": path})

        self._progress.progress(message="Ranking candidate moments...")
        changes = scene_detection.compute_change_scores(frames)
        ranked = sorted(changes, key=lambda sample: -sample.change_score)[:max_moments]
        ranked.sort(key=lambda sample: sample.timestamp_seconds)

        result: list[dict] = [
            {
                "timestamp_seconds": sample.timestamp_seconds,
                "frame_index": sample.frame_index,
                "change_score": sample.change_score,
            }
            for sample in ranked
        ]

        if include_explanation and ranked:
            self._progress.progress(message="Waiting for Video model...")

            by_index = {frame.index: frame for frame in frames}
            selected_frames = [
                by_index[sample.frame_index]
                for sample in ranked
                if sample.frame_index in by_index
            ]
            frames_base64 = tuple(
                frame_io.encode_frame_base64(frame.image) for frame in selected_frames
            )
            explanation = engine.analyze_frames_with_provider(
                self._brain,
                self._provider_capability_id,
                frames_base64,
                "These frames were flagged as the video's most visually "
                "significant moments. Briefly explain why each might be "
                "important, in the same order.",
                execution_requirements=execution_requirements,
            )

            for entry in result:
                entry.setdefault("explanation", None)
            result_with_explanation = {"key_moments": result, "explanation": explanation}
            self._progress.completed(message="Completed.")
            return ToolResponse(result=result_with_explanation, attributes={"path": path})

        self._progress.completed(message="Completed.")

        return ToolResponse(result={"key_moments": result}, attributes={"path": path})
