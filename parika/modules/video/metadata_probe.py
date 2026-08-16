"""
PARIKA Video Module - Deterministic Metadata Extraction

Backs `video.extract_metadata`. Two layers, both deterministic, never
a model call:

1. `probe_container_properties()` -- always available (once the
   `video` extra's `opencv-python-headless` is installed): duration/
   width/height/frame_rate/frame_count/codec (best-effort, from the
   container's own FourCC) via `frame_io.read_properties()`, plus
   `container_format` from the file extension (the same deterministic
   extension-based technique `document/format_detection.py` already
   establishes for document formats).

2. `probe_with_ffprobe()` -- an optional, best-effort enhancement
   (accurate codec name, bitrate, audio-stream presence) via the
   system `ffprobe` utility, invoked exclusively through the existing,
   unmodified Shell Tool's `tool.shell_execute` Capability -- never a
   new `subprocess` call of this Module's own, exactly mirroring
   `parika/modules/repository_intelligence/repository/git_reader.py`'s
   own fixed, read-only, argv-form external-command precedent. When
   `ffprobe` or the Shell Tool itself is unavailable, this layer is
   silently skipped (never a crash) and `probe_container_properties()`'s
   own values are reported as-is -- `bitrate`/`has_audio_stream` then
   honestly report `None` rather than a guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager

from . import frame_io
from .video_model import VideoMetadata

SHELL_EXECUTE_TOOL_ID = "tool.shell_execute"

_EXTENSION_TO_CONTAINER_FORMAT: dict[str, str] = {
    ".mp4": "mp4",
    ".m4v": "mp4",
    ".mov": "mov",
    ".mkv": "matroska",
    ".webm": "webm",
    ".avi": "avi",
    ".wmv": "asf",
    ".flv": "flv",
    ".mpg": "mpeg",
    ".mpeg": "mpeg",
    ".3gp": "3gpp",
    ".ogv": "ogg",
}


def detect_container_format(path: str) -> str | None:
    """Deterministic, extension-based container-format guess -- never raises."""

    for suffix, container_format in _EXTENSION_TO_CONTAINER_FORMAT.items():
        if path.lower().endswith(suffix):
            return container_format

    return None


def probe_container_properties(resolved_path: str) -> VideoMetadata:
    """
    Build a `VideoMetadata` snapshot from `cv2.VideoCapture` alone --
    always available once `opencv-python-headless` is installed, with
    `bitrate`/`has_audio_stream` left `None` (OpenCV cannot report
    either) pending `probe_with_ffprobe()`'s optional enhancement.
    """

    capture = frame_io.open_capture(resolved_path)

    try:
        properties = frame_io.read_properties(capture)
    finally:
        capture.release()

    duration_seconds = None
    if properties.frame_count is not None and properties.frame_rate:
        duration_seconds = round(properties.frame_count / properties.frame_rate, 3)

    return VideoMetadata(
        path=resolved_path,
        duration_seconds=duration_seconds,
        width=properties.width,
        height=properties.height,
        frame_rate=properties.frame_rate,
        frame_count=properties.frame_count,
        codec=properties.fourcc,
        container_format=detect_container_format(resolved_path),
        bitrate=None,
        has_video_stream=properties.width is not None and properties.height is not None,
        has_audio_stream=None,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class FfprobeEnhancement:
    """Best-effort `ffprobe` enhancement -- see `probe_with_ffprobe()`."""

    duration_seconds: float | None = None
    codec: str | None = None
    container_format: str | None = None
    bitrate: int | None = None
    has_audio_stream: bool | None = None


def probe_with_ffprobe(
    tool_manager: ToolManager, resolved_path: str
) -> FfprobeEnhancement | None:
    """
    Best-effort `ffprobe -show_format -show_streams` enhancement,
    invoked exclusively through `tool.shell_execute`. Returns `None`
    on any failure (binary missing, Shell Tool disabled, malformed
    output) -- callers must treat this purely as an optional
    enhancement layered on top of `probe_container_properties()`,
    never a required step.
    """

    try:
        response = tool_manager.execute(
            SHELL_EXECUTE_TOOL_ID,
            ToolRequest(
                arguments={
                    "command": [
                        "ffprobe",
                        "-v",
                        "error",
                        "-print_format",
                        "json",
                        "-show_format",
                        "-show_streams",
                        resolved_path,
                    ]
                }
            ),
        )
    except Exception:
        return None

    result = response.result

    if not isinstance(result, dict) or result.get("exit_code") != 0:
        return None

    try:
        parsed = json.loads(str(result.get("stdout", "")))
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(parsed, dict):
        return None

    format_info = parsed.get("format") if isinstance(parsed.get("format"), dict) else {}
    streams = parsed.get("streams") if isinstance(parsed.get("streams"), list) else []

    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), None
    )
    has_audio_stream = any(stream.get("codec_type") == "audio" for stream in streams)

    duration_raw = format_info.get("duration")
    bitrate_raw = format_info.get("bit_rate")

    return FfprobeEnhancement(
        duration_seconds=float(duration_raw) if duration_raw is not None else None,
        codec=(video_stream or {}).get("codec_name"),
        container_format=format_info.get("format_name", "").split(",")[0] or None,
        bitrate=int(bitrate_raw) if bitrate_raw is not None else None,
        has_audio_stream=has_audio_stream,
    )


def merge_ffprobe_enhancement(
    metadata: VideoMetadata, enhancement: FfprobeEnhancement | None
) -> VideoMetadata:
    """Layer `enhancement`'s values over `metadata`'s own, preferring `ffprobe` where present."""

    if enhancement is None:
        return metadata

    from dataclasses import replace

    return replace(
        metadata,
        duration_seconds=enhancement.duration_seconds or metadata.duration_seconds,
        codec=enhancement.codec or metadata.codec,
        container_format=enhancement.container_format or metadata.container_format,
        bitrate=enhancement.bitrate,
        has_audio_stream=enhancement.has_audio_stream,
    )
