"""
PARIKA Video Module - Shared ToolDriver Request Helpers

Small argument-parsing/orchestration helpers reused by every `video.*`
ToolDriver in this Module, to avoid repeating the same
"validate path -> probe properties -> resolve sampling -> decode
frames" sequence in each one. No Capability/registration logic lives
here (see `module_driver.py`).
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest

from . import engine, frame_io
from .exceptions import VideoReadError
from .frame_io import DecodedFrame, VideoProperties
from .sampling import SamplingRequest, resolve_indices


def require_path(request: ToolRequest) -> str:
    path = str(request.arguments.get("path", "")).strip()

    if not path:
        raise VideoReadError("request.arguments['path'] must be a non-empty string.")

    return path


def sampling_request_from_arguments(request: ToolRequest) -> SamplingRequest:
    arguments = request.arguments

    frame_indices = arguments.get("frame_indices")
    timestamps_seconds = arguments.get("timestamps_seconds")

    return SamplingRequest(
        frame_indices=(
            tuple(int(index) for index in frame_indices) if frame_indices else None
        ),
        timestamps_seconds=(
            tuple(float(value) for value in timestamps_seconds)
            if timestamps_seconds
            else None
        ),
        interval_seconds=(
            float(arguments["interval_seconds"])
            if arguments.get("interval_seconds") is not None
            else None
        ),
        max_frames=(
            int(arguments["max_frames"]) if arguments.get("max_frames") is not None else None
        ),
        focus_timestamp_seconds=(
            float(arguments["focus_timestamp_seconds"])
            if arguments.get("focus_timestamp_seconds") is not None
            else None
        ),
        focus_window_seconds=(
            float(arguments["focus_window_seconds"])
            if arguments.get("focus_window_seconds") is not None
            else None
        ),
    )


def probe_properties(resolved_path: str) -> VideoProperties:
    capture = frame_io.open_capture(resolved_path)

    try:
        return frame_io.read_properties(capture)
    finally:
        capture.release()


@dataclass(frozen=True, slots=True, kw_only=True)
class SampledVideo:
    """Everything one ToolDriver call needs after path validation/sampling/decoding."""

    resolved_path: str
    properties: VideoProperties
    frames: list[DecodedFrame]


def sample_and_decode(
    brain: Brain,
    path: str,
    sampling_request: SamplingRequest,
    *,
    default_max_frames: int,
    hard_cap: int,
) -> SampledVideo:
    """
    The common "validate -> probe -> resolve indices -> decode"
    sequence: validates `path` through `engine.resolve_video_path()`,
    probes container properties, resolves concrete frame indices via
    `sampling.resolve_indices()` (honoring any caller override), and
    decodes exactly those frames.
    """

    resolved_path = engine.resolve_video_path(brain, path)
    properties = probe_properties(resolved_path)

    indices = resolve_indices(
        sampling_request,
        frame_count=properties.frame_count,
        frame_rate=properties.frame_rate,
        default_max_frames=default_max_frames,
        hard_cap=hard_cap,
    )

    frames = frame_io.extract_frames(
        resolved_path, indices, frame_rate=properties.frame_rate
    )

    return SampledVideo(resolved_path=resolved_path, properties=properties, frames=frames)
