"""
PARIKA Video Module - Deterministic Keyframe Selection

Pure arithmetic built on `scene_detection.py` -- no model call. Backs
`video.extract_keyframes`: one representative frame per detected shot
(the frame roughly centered within each shot's own span, since a
shot's middle frame is typically more representative than its first
frame, which may still be mid-transition), falling back to uniform
sampling when too few shot boundaries are detected (e.g. a
single-shot, mostly static video).
"""

from __future__ import annotations

from .video_model import VideoSegment


def keyframe_indices_from_segments(
    segments: tuple[VideoSegment, ...],
    *,
    frame_rate: float,
    max_keyframes: int,
) -> list[int]:
    """One representative (mid-point) frame index per segment, capped at `max_keyframes`."""

    candidates: list[int] = []

    for segment in segments:
        mid_seconds = (segment.start_seconds + segment.end_seconds) / 2
        mid_frame = round(mid_seconds * frame_rate)
        candidates.append(max(segment.start_frame_index, min(mid_frame, segment.end_frame_index)))

    if len(candidates) > max_keyframes:
        step = len(candidates) / max_keyframes
        candidates = [candidates[round(index * step)] for index in range(max_keyframes)]

    return sorted(set(candidates))
