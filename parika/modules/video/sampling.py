"""
PARIKA Video Module - Deterministic Adaptive Frame Sampling

Pure arithmetic -- no decoding, no model call. Every `video.*`
Capability that needs frames picks *how many* and *which* indices
through the functions here rather than a single fixed strategy,
satisfying the "implement adaptive frame sampling" requirement: the
strategy considers duration, frame rate, requested operation, and an
optional maximum-frame-count/focus-timestamp override, never
extracting every frame by default.
"""

from __future__ import annotations

from dataclasses import dataclass


def _frame_rate_or_default(frame_rate: float | None) -> float:
    return frame_rate if frame_rate and frame_rate > 0 else 25.0


def _clamp_count(frame_count: int | None, requested: int) -> int:
    if frame_count is None or frame_count <= 0:
        return max(1, requested)

    return max(1, min(requested, frame_count))


def uniform_indices(
    *, frame_count: int | None, max_frames: int
) -> list[int]:
    """
    Evenly spaced frame indices spanning the whole video -- the
    default "representative frame set" strategy (used by
    `video.describe_video`/`video.summarize_video`/
    `video.classify_video`/`video.extract_keyframes`'s deterministic
    seed set).
    """

    count = _clamp_count(frame_count, max_frames)

    if frame_count is None or frame_count <= 1:
        return [0]

    if count == 1:
        return [frame_count // 2]

    step = (frame_count - 1) / (count - 1)
    return sorted({round(index * step) for index in range(count)})


def interval_indices(
    *, frame_count: int | None, frame_rate: float | None, interval_seconds: float
) -> list[int]:
    """One frame every `interval_seconds` of playback time."""

    if frame_count is None or frame_count <= 0:
        return [0]

    rate = _frame_rate_or_default(frame_rate)
    step_frames = max(1, round(interval_seconds * rate))
    return list(range(0, frame_count, step_frames))


def timestamp_indices(
    *, frame_rate: float | None, frame_count: int | None, timestamps_seconds: list[float]
) -> list[int]:
    """Explicit timestamps -> nearest frame indices, clamped to range."""

    rate = _frame_rate_or_default(frame_rate)
    last_index = (frame_count - 1) if frame_count and frame_count > 0 else None

    indices: list[int] = []
    for timestamp in timestamps_seconds:
        index = max(0, round(timestamp * rate))
        if last_index is not None:
            index = min(index, last_index)
        indices.append(index)

    return sorted(set(indices))


def dense_indices(
    *,
    frame_count: int | None,
    frame_rate: float | None,
    target_fps: float,
    max_frames: int,
) -> list[int]:
    """
    Denser-than-uniform sampling targeting `target_fps` sampled
    frames per second of playback -- used by capabilities that need
    finer temporal resolution (object tracking, motion detection,
    shot/scene-change detection) than a handful of representative
    frames can provide, but still bounded by `max_frames`.
    """

    if frame_count is None or frame_count <= 0:
        return [0]

    rate = _frame_rate_or_default(frame_rate)
    step_frames = max(1, round(rate / max(target_fps, 0.1)))
    indices = list(range(0, frame_count, step_frames))

    if len(indices) > max_frames:
        return uniform_indices(frame_count=frame_count, max_frames=max_frames)

    return indices


def focus_window_indices(
    *,
    frame_count: int | None,
    frame_rate: float | None,
    focus_timestamp_seconds: float,
    window_seconds: float,
    max_frames: int,
) -> list[int]:
    """
    Frames drawn from a window centered on `focus_timestamp_seconds`
    -- used for timestamp-specific questions (`video.answer_question`)
    and `video.detect_key_moments`'s own candidate refinement, instead
    of sampling the entire video for a question about one moment.
    """

    rate = _frame_rate_or_default(frame_rate)
    last_index = (frame_count - 1) if frame_count and frame_count > 0 else None

    start_seconds = max(0.0, focus_timestamp_seconds - window_seconds / 2)
    end_seconds = focus_timestamp_seconds + window_seconds / 2

    start_index = max(0, round(start_seconds * rate))
    end_index = round(end_seconds * rate)

    if last_index is not None:
        start_index = min(start_index, last_index)
        end_index = min(end_index, last_index)

    if end_index <= start_index:
        return [start_index]

    span = end_index - start_index + 1
    count = min(max_frames, span)
    step = max(1, span // max(count, 1))
    return list(range(start_index, end_index + 1, step))[:max_frames]


@dataclass(frozen=True, slots=True, kw_only=True)
class SamplingRequest:
    """
    Caller-supplied sampling override, shared by every `video.*`
    Tool's optional `frame_indices`/`timestamps_seconds`/
    `interval_seconds`/`max_frames` arguments. When every field is
    `None`, the driver's own operation-specific default strategy
    (`uniform_indices()`, `dense_indices()`, ...) applies.
    """

    frame_indices: tuple[int, ...] | None = None
    timestamps_seconds: tuple[float, ...] | None = None
    interval_seconds: float | None = None
    max_frames: int | None = None
    focus_timestamp_seconds: float | None = None
    focus_window_seconds: float | None = None


def resolve_indices(
    request: SamplingRequest,
    *,
    frame_count: int | None,
    frame_rate: float | None,
    default_max_frames: int,
    hard_cap: int,
) -> list[int]:
    """
    Resolve a `SamplingRequest` into concrete frame indices, honoring
    an explicit override first (indices > timestamps > interval),
    otherwise falling back to `uniform_indices()` bounded by
    `default_max_frames`/`hard_cap` -- the common entry point most
    ToolDrivers in this Module call.
    """

    max_frames = min(request.max_frames or default_max_frames, hard_cap)

    if request.frame_indices:
        indices = sorted(set(request.frame_indices))[:max_frames]
        return indices or [0]

    if request.timestamps_seconds:
        return timestamp_indices(
            frame_rate=frame_rate,
            frame_count=frame_count,
            timestamps_seconds=list(request.timestamps_seconds),
        )[:max_frames]

    if request.interval_seconds:
        indices = interval_indices(
            frame_count=frame_count,
            frame_rate=frame_rate,
            interval_seconds=request.interval_seconds,
        )
        return indices[:max_frames] if len(indices) > max_frames else indices

    if request.focus_timestamp_seconds is not None:
        return focus_window_indices(
            frame_count=frame_count,
            frame_rate=frame_rate,
            focus_timestamp_seconds=request.focus_timestamp_seconds,
            window_seconds=request.focus_window_seconds or 6.0,
            max_frames=max_frames,
        )

    return uniform_indices(frame_count=frame_count, max_frames=max_frames)
