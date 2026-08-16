"""
PARIKA Video Module - Normalized Data Model

Pure-data, frozen dataclasses shared by every `video.*` ToolDriver --
no I/O, no model calls, no Brain/Goal/Capability concept. Mirrors
`parika/modules/document/document_model.py`'s own shape: one common,
JSON-serializable representation (`to_result_dict()`) every downstream
Tool builds its `ToolResponse.result` on top of, rather than each
driver inventing its own ad hoc dict shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True, kw_only=True)
class VideoMetadata:
    """
    Deterministic video metadata -- see `metadata_probe.py`'s
    `probe_metadata()`, the sole producer of this dataclass. Backs
    `video.extract_metadata` and is reused internally (never
    re-derived) by every other Capability that needs the video's
    duration/fps/frame_count/dimensions before sampling frames.
    """

    path: str
    duration_seconds: float | None
    width: int | None
    height: int | None
    frame_rate: float | None
    frame_count: int | None
    codec: str | None
    container_format: str | None
    bitrate: int | None
    has_video_stream: bool
    has_audio_stream: bool | None
    """`None` when audio-stream presence could not be determined
    (OpenCV's `VideoCapture` cannot report audio streams at all;
    `None` is reported honestly rather than guessing `False`)."""

    def to_result_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "frame_rate": self.frame_rate,
            "frame_count": self.frame_count,
            "codec": self.codec,
            "container_format": self.container_format,
            "bitrate": self.bitrate,
            "has_video_stream": self.has_video_stream,
            "has_audio_stream": self.has_audio_stream,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class FrameDescriptor:
    """
    One sampled frame's identity -- index/timestamp only, never the
    decoded pixel data itself (that stays in-memory, as a Pillow
    `Image`, only for as long as one driver call needs it). Every
    `video.*` Capability that returns per-frame results describes
    each frame with this shape.
    """

    index: int
    timestamp_seconds: float

    def to_result_dict(self) -> dict[str, object]:
        return {"frame_index": self.index, "timestamp_seconds": self.timestamp_seconds}


@dataclass(frozen=True, slots=True, kw_only=True)
class ShotBoundary:
    """One detected shot boundary -- see `scene_detection.py`."""

    frame_index: int
    timestamp_seconds: float
    change_score: float

    def to_result_dict(self) -> dict[str, object]:
        return {
            "frame_index": self.frame_index,
            "timestamp_seconds": self.timestamp_seconds,
            "change_score": self.change_score,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class VideoSegment:
    """One temporal segment bounded by two shot boundaries (or the
    video's own start/end) -- see `scene_detection.py`/`driver_timeline.py`."""

    start_seconds: float
    end_seconds: float
    start_frame_index: int
    end_frame_index: int

    def to_result_dict(self) -> dict[str, object]:
        return {
            "start_seconds": self.start_seconds,
            "end_seconds": self.end_seconds,
            "start_frame_index": self.start_frame_index,
            "end_frame_index": self.end_frame_index,
            "duration_seconds": round(self.end_seconds - self.start_seconds, 3),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TimelineEntry:
    """One `video.generate_timeline` entry."""

    timestamp_seconds: float
    frame_index: int
    is_scene_change: bool
    observations: str = ""
    visible_text: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_result_dict(self) -> dict[str, object]:
        return {
            "timestamp_seconds": self.timestamp_seconds,
            "frame_index": self.frame_index,
            "is_scene_change": self.is_scene_change,
            "observations": self.observations,
            "visible_text": self.visible_text,
            "tags": list(self.tags),
        }
