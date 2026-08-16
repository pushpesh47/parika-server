"""
PARIKA Video Module - Deterministic Shot/Scene Detection & Segmentation

Pure frame-comparison algorithms built on `hashing.change_score()` --
no model call. Backs `video.detect_scene_changes`, `video.detect_shots`,
`video.segment_video`, and contributes the candidate list
`video.detect_key_moments`/`video.generate_timeline` refine further.

Terminology used throughout this Module (kept deliberately simple for
a v1 without ML-based shot/scene classification):

- A "shot boundary" is any consecutive-sampled-frame pair whose
  `hashing.change_score()` exceeds the configured threshold -- an
  abrupt visual transition (cut, fade, hard scene change).
- A "segment" is the span between two consecutive shot boundaries
  (or the video's own start/end) -- `video.segment_video`'s output.
  This v1 does not attempt semantic scene *grouping* of multiple
  shots into one narrative scene (no classical algorithm can do that
  reliably) -- `video.detect_scene_changes` and `video.detect_shots`
  therefore share the same deterministic boundary detector, exactly
  as the task's own capability descriptions allow ("prefer
  deterministic frame comparison before using an LLM").
"""

from __future__ import annotations

from dataclasses import dataclass

from . import hashing
from .frame_io import DecodedFrame
from .video_model import ShotBoundary, VideoSegment

DEFAULT_CHANGE_THRESHOLD = 0.35


@dataclass(frozen=True, slots=True, kw_only=True)
class ChangeSample:
    """One consecutive-sampled-frame comparison -- see `compute_change_scores()`."""

    frame_index: int
    timestamp_seconds: float
    change_score: float


def compute_change_scores(frames: list[DecodedFrame]) -> list[ChangeSample]:
    """
    Compute `hashing.change_score()` between every consecutive pair of
    `frames` (already decoded, in ascending index order). The first
    frame has no predecessor and is never itself a boundary
    candidate.
    """

    samples: list[ChangeSample] = []

    for previous, current in zip(frames, frames[1:]):
        score = hashing.change_score(previous.image, current.image)
        samples.append(
            ChangeSample(
                frame_index=current.index,
                timestamp_seconds=current.timestamp_seconds,
                change_score=score.overall,
            )
        )

    return samples


def detect_boundaries(
    frames: list[DecodedFrame], *, threshold: float = DEFAULT_CHANGE_THRESHOLD
) -> tuple[ShotBoundary, ...]:
    """Threshold `compute_change_scores()` into `ShotBoundary` instances."""

    return tuple(
        ShotBoundary(
            frame_index=sample.frame_index,
            timestamp_seconds=sample.timestamp_seconds,
            change_score=sample.change_score,
        )
        for sample in compute_change_scores(frames)
        if sample.change_score >= threshold
    )


def segments_from_boundaries(
    boundaries: tuple[ShotBoundary, ...],
    *,
    first_frame_index: int,
    first_timestamp_seconds: float,
    last_frame_index: int,
    last_timestamp_seconds: float,
) -> tuple[VideoSegment, ...]:
    """
    Split `[first_timestamp_seconds, last_timestamp_seconds]` into
    contiguous `VideoSegment`s at every boundary -- `video.segment_video`'s
    primary output, reusing `detect_boundaries()` rather than a second
    segmentation algorithm.
    """

    cut_points = [(first_frame_index, first_timestamp_seconds)]
    cut_points.extend((boundary.frame_index, boundary.timestamp_seconds) for boundary in boundaries)
    cut_points.append((last_frame_index, last_timestamp_seconds))

    segments: list[VideoSegment] = []
    for (start_frame, start_time), (end_frame, end_time) in zip(cut_points, cut_points[1:]):
        if end_time <= start_time:
            continue

        segments.append(
            VideoSegment(
                start_seconds=start_time,
                end_seconds=end_time,
                start_frame_index=start_frame,
                end_frame_index=end_frame,
            )
        )

    return tuple(segments)
