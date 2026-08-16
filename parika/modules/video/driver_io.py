"""
PARIKA Video Module - I/O Drivers

`video.read_video`, `video.extract_metadata`, `video.extract_frames`,
`video.extract_keyframes`, and `video.extract_thumbnails`. All five
are 100% deterministic -- no model call, ever (per the task's own
"Do not use an LLM for: metadata, frame extraction, thumbnails, ..."
instruction).
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, frame_io, keyframes, metadata_probe, scene_detection, thumbnails
from .config import VideoToolConfig
from .exceptions import VideoFrameExtractionError
from .driver_common import (
    probe_properties,
    require_path,
    sample_and_decode,
    sampling_request_from_arguments,
)
from .sampling import SamplingRequest, dense_indices


class VideoReadToolDriver:
    """
    `ToolDriver` implementing `video.read_video`: validates the path
    and reports the video's own basic, cheaply-probed container
    properties -- the "normalized video representation" every other
    Capability in this Module can build on. Unlike
    `video.extract_metadata`, this never attempts the optional
    `ffprobe` enhancement (kept intentionally cheap/fast, matching
    the task's own "do not duplicate filesystem functionality
    unnecessarily" instruction for this specific Capability).
    """

    def __init__(self, *, brain: Brain, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._progress = progress_reporter or NullProgressReporter("video.read_video")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)

        self._progress.started(message="Validating video...")

        resolved_path = engine.resolve_video_path(self._brain, path)
        capture = frame_io.open_capture(resolved_path)
        try:
            properties = frame_io.read_properties(capture)
        finally:
            capture.release()

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "path": resolved_path,
                "readable": True,
                "width": properties.width,
                "height": properties.height,
                "frame_rate": properties.frame_rate,
                "frame_count": properties.frame_count,
                "container_format": metadata_probe.detect_container_format(resolved_path),
            },
            attributes={"path": path},
        )


class VideoMetadataToolDriver:
    """`ToolDriver` implementing `video.extract_metadata`."""

    def __init__(
        self,
        *,
        brain: Brain,
        tool_manager: ToolManager,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._tool_manager = tool_manager
        self._progress = progress_reporter or NullProgressReporter("video.extract_metadata")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)

        self._progress.started(message="Probing video metadata...")

        resolved_path = engine.resolve_video_path(self._brain, path)
        metadata = metadata_probe.probe_container_properties(resolved_path)

        self._progress.progress(message="Checking for ffprobe enhancement...")
        enhancement = metadata_probe.probe_with_ffprobe(self._tool_manager, resolved_path)
        metadata = metadata_probe.merge_ffprobe_enhancement(metadata, enhancement)

        self._progress.completed(message="Completed.")

        return ToolResponse(result=metadata.to_result_dict(), attributes={"path": path})


class VideoFrameExtractionToolDriver:
    """
    `ToolDriver` implementing `video.extract_frames`. Supports
    `frame_indices`/`timestamps_seconds`/`interval_seconds`/
    `max_frames` overrides (see `sampling.SamplingRequest`); defaults
    to a bounded, evenly-spaced sample rather than every frame.
    `include_image_data` (default `False`) opts into returning each
    frame's base64-encoded pixel data -- kept opt-in so the common
    case (frame identity/timing only) stays lean.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        config: VideoToolConfig,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.extract_frames")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        include_image_data = bool(request.arguments.get("include_image_data", False))
        sampling_request = sampling_request_from_arguments(request)

        self._progress.started(message="Sampling frames...")

        sampled = sample_and_decode(
            self._brain,
            path,
            sampling_request,
            default_max_frames=self._config.max_sample_frames,
            hard_cap=self._config.max_sample_frames,
        )

        self._progress.progress(message="Decoding frames...")

        frames_result = []
        for frame in sampled.frames:
            entry: dict = {"frame_index": frame.index, "timestamp_seconds": frame.timestamp_seconds}
            if include_image_data:
                entry["image_base64"] = frame_io.encode_frame_base64(frame.image)
                entry["image_format"] = "JPEG"
            frames_result.append(entry)

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"frames": frames_result, "frame_count_returned": len(frames_result)},
            attributes={"path": path},
        )


class VideoKeyframeToolDriver:
    """
    `ToolDriver` implementing `video.extract_keyframes`: densely
    samples the video, detects shot boundaries
    (`scene_detection.detect_boundaries()`), and selects one
    representative frame per shot (`keyframes.keyframe_indices_from_segments()`)
    -- deterministic, never a model call.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        config: VideoToolConfig,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.extract_keyframes")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        include_image_data = bool(request.arguments.get("include_image_data", False))
        max_keyframes = int(request.arguments.get("max_keyframes", self._config.describe_frame_count * 2))

        self._progress.started(message="Sampling candidate frames...")

        resolved_path = engine.resolve_video_path(self._brain, path)
        properties = probe_properties(resolved_path)
        indices = dense_indices(
            frame_count=properties.frame_count,
            frame_rate=properties.frame_rate,
            target_fps=self._config.dense_sample_target_fps,
            max_frames=self._config.max_sample_frames,
        )
        candidate_frames = frame_io.extract_frames(
            resolved_path, indices, frame_rate=properties.frame_rate
        )

        if len(candidate_frames) < 2:
            keyframe_indices = [frame.index for frame in candidate_frames] or [0]
        else:
            self._progress.progress(message="Detecting shot boundaries...")
            boundaries = scene_detection.detect_boundaries(
                candidate_frames, threshold=self._config.scene_change_threshold
            )
            segments = scene_detection.segments_from_boundaries(
                boundaries,
                first_frame_index=candidate_frames[0].index,
                first_timestamp_seconds=candidate_frames[0].timestamp_seconds,
                last_frame_index=candidate_frames[-1].index,
                last_timestamp_seconds=candidate_frames[-1].timestamp_seconds,
            )
            keyframe_indices = keyframes.keyframe_indices_from_segments(
                segments,
                frame_rate=properties.frame_rate or 25.0,
                max_keyframes=max_keyframes,
            )

        by_index = {frame.index: frame for frame in candidate_frames}
        missing = [index for index in keyframe_indices if index not in by_index]
        if missing:
            for frame in frame_io.extract_frames(
                resolved_path, missing, frame_rate=properties.frame_rate
            ):
                by_index[frame.index] = frame

        self._progress.completed(message="Completed.")

        result_frames = []
        for index in keyframe_indices:
            frame = by_index.get(index)
            if frame is None:
                continue

            entry: dict = {"frame_index": frame.index, "timestamp_seconds": frame.timestamp_seconds}
            if include_image_data:
                entry["image_base64"] = frame_io.encode_frame_base64(frame.image)
                entry["image_format"] = "JPEG"
            result_frames.append(entry)

        return ToolResponse(
            result={"keyframes": result_frames, "keyframe_count": len(result_frames)},
            attributes={"path": path},
        )


class VideoThumbnailToolDriver:
    """
    `ToolDriver` implementing `video.extract_thumbnails`: a contact-
    sheet grid of uniformly-sampled frames via
    `thumbnails.build_contact_sheet()` -- deterministic, never a
    model call.
    """

    def __init__(
        self,
        *,
        brain: Brain,
        config: VideoToolConfig,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.extract_thumbnails")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        columns = int(request.arguments.get("columns", self._config.thumbnail_columns))
        rows = int(request.arguments.get("rows", self._config.thumbnail_rows))
        cell_width = int(request.arguments.get("cell_width", self._config.thumbnail_cell_width))

        self._progress.started(message="Sampling frames...")

        sampled = sample_and_decode(
            self._brain,
            path,
            SamplingRequest(max_frames=columns * rows),
            default_max_frames=columns * rows,
            hard_cap=columns * rows,
        )

        if not sampled.frames:
            raise VideoFrameExtractionError(
                "No frames could be decoded to build a contact sheet."
            )

        self._progress.progress(message="Building contact sheet...")

        sheet = thumbnails.build_contact_sheet(
            [frame.image for frame in sampled.frames], columns=columns, cell_width=cell_width
        )
        sheet_base64 = frame_io.encode_frame_base64(sheet, image_format="JPEG")

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "image_base64": sheet_base64,
                "image_format": "JPEG",
                "columns": columns,
                "rows": rows,
                "frames": [
                    {"frame_index": frame.index, "timestamp_seconds": frame.timestamp_seconds}
                    for frame in sampled.frames
                ],
            },
            attributes={"path": path},
        )
