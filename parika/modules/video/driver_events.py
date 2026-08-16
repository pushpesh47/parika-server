"""
PARIKA Video Module - Event & Action Analysis Drivers

`video.detect_events` and `video.detect_actions`. `detect_events`
generates deterministic candidates first (scene changes, motion
spikes, black-frame transitions) and only escalates to a Provider
Capability when the caller wants semantic labeling; `detect_actions`
genuinely requires a multimodal model (no classical algorithm
recognizes actions), so it always calls its own
`video.provider_detect_actions` Capability on the flagged segments'
frames, and always reports a `confidence` derived from how much
visual change backs the claim.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, frame_io, motion, quality, scene_detection
from .config import VideoToolConfig
from .driver_common import probe_properties, require_path
from .exceptions import VideoReadError
from .sampling import dense_indices

_DEFAULT_MAX_EVENTS = 15


def _sample_dense(brain: Brain, path: str, config: VideoToolConfig):
    resolved_path = engine.resolve_video_path(brain, path)
    properties = probe_properties(resolved_path)
    indices = dense_indices(
        frame_count=properties.frame_count,
        frame_rate=properties.frame_rate,
        target_fps=config.dense_sample_target_fps,
        max_frames=config.max_sample_frames,
    )
    frames = frame_io.extract_frames(resolved_path, indices, frame_rate=properties.frame_rate)
    return resolved_path, properties, frames


class VideoDetectEventsToolDriver:
    """
    `ToolDriver` implementing `video.detect_events`: deterministically
    flags scene-change transitions, motion spikes, and black-frame
    transitions as candidate events (never a model call for the
    candidates themselves); optionally asks
    `video.provider_detect_key_moments`-style semantic labeling is
    intentionally *not* invoked here to keep this Capability's
    default cost at zero model calls -- callers wanting semantic
    event narration should combine this Capability's timestamps with
    `video.describe_video`'s own `timestamp_seconds` focus argument.
    """

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_events")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        max_events = int(request.arguments.get("max_events", _DEFAULT_MAX_EVENTS))

        self._progress.started(message="Sampling frames...")
        _, _, frames = _sample_dense(self._brain, path, self._config)

        if len(frames) < 2:
            self._progress.completed(message="Completed.")
            return ToolResponse(result={"events": []}, attributes={"path": path})

        self._progress.progress(message="Detecting candidate events...")

        events: list[dict] = []

        for boundary in scene_detection.detect_boundaries(
            frames, threshold=self._config.scene_change_threshold
        ):
            events.append(
                {
                    "event_type": "scene_change",
                    "timestamp_seconds": boundary.timestamp_seconds,
                    "frame_index": boundary.frame_index,
                    "score": boundary.change_score,
                }
            )

        for previous, current in zip(frames, frames[1:]):
            motion_result = motion.detect_motion(
                previous.image,
                current.image,
                pixel_threshold=self._config.motion_pixel_threshold,
                area_ratio_threshold=self._config.motion_area_ratio_threshold,
            )
            if motion_result.has_motion:
                events.append(
                    {
                        "event_type": "motion_spike",
                        "timestamp_seconds": current.timestamp_seconds,
                        "frame_index": current.index,
                        "score": motion_result.changed_pixel_ratio,
                    }
                )

            black_before = quality.detect_black_frame(
                previous.image, threshold=self._config.black_frame_brightness_threshold
            )
            black_after = quality.detect_black_frame(
                current.image, threshold=self._config.black_frame_brightness_threshold
            )
            if black_before.is_black != black_after.is_black:
                events.append(
                    {
                        "event_type": "black_frame_transition",
                        "timestamp_seconds": current.timestamp_seconds,
                        "frame_index": current.index,
                        "score": 1.0,
                    }
                )

        events.sort(key=lambda event: -event["score"])
        events = events[:max_events]
        events.sort(key=lambda event: event["timestamp_seconds"])

        self._progress.completed(message="Completed.")

        return ToolResponse(result={"events": events}, attributes={"path": path})


class VideoDetectActionsToolDriver:
    """
    `ToolDriver` implementing `video.detect_actions`: densely samples
    the video and asks the `video.provider_detect_actions` Capability
    to recognize actions -- genuinely requires a multimodal model, so
    this Capability never claims fine-grained action recognition
    beyond what the selected Provider model reports, and always
    returns a `confidence` derived from the deterministic motion level
    backing the request (low motion -> low confidence any claimed
    action is meaningful, regardless of what the model says).
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
        self._progress = progress_reporter or NullProgressReporter("video.detect_actions")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Sampling frames...")
        _, _, frames = _sample_dense(self._brain, path, self._config)

        if not frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        motion_scores = [
            motion.detect_motion(previous.image, current.image).changed_pixel_ratio
            for previous, current in zip(frames, frames[1:])
        ]
        average_motion = sum(motion_scores) / len(motion_scores) if motion_scores else 0.0
        confidence = round(min(1.0, average_motion * 8), 4)

        self._progress.progress(message="Waiting for Video model...")

        frames_base64 = tuple(frame_io.encode_frame_base64(frame.image) for frame in frames)
        stamps = ", ".join(f"{frame.timestamp_seconds:.1f}s" for frame in frames)
        instruction = (
            f"These frames were sampled in order from a video, at: {stamps}. "
            "Identify any recognizable actions or events taking place, in "
            "chronological order. If you are not confident, say so plainly "
            "rather than guessing."
        )

        text = engine.analyze_frames_with_provider(
            self._brain,
            self._provider_capability_id,
            frames_base64,
            instruction,
            execution_requirements=execution_requirements,
        )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={"actions": text, "confidence": confidence, "average_motion_ratio": round(average_motion, 4)},
            attributes={"path": path},
        )
