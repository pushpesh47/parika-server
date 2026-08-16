"""
PARIKA Video Module - Video Understanding Drivers

`video.describe_video`, `video.summarize_video`, `video.answer_question`,
and `video.classify_video`. Each follows the task's own recommended
pipeline: adaptively sample a bounded, representative set of frames
(never "hundreds of frames"), then invoke exactly one multimodal
Provider Goal carrying every sampled frame in one provider-independent
`ChatMessage` (its `images` tuple accepts more than one -- see
`engine.py`) -- one model call per Tool invocation, never one call per
frame, which is both the "minimize model calls" requirement and
strictly more capable of genuine *temporal* reasoning than describing
each frame in isolation and concatenating the results would be.

`include_ocr` (optional, default `False`) opts into an additional
deterministic-adjacent step -- extracting visible text from the
sampled frames via `engine.extract_text_from_frame()` (OCR's own
Provider Capability, reused, never reimplemented) and folding it into
the instruction sent to the video-understanding model -- for
questions that concern on-screen text. Whether that is needed is a
judgment call left to the calling model when it fills in this Tool's
own arguments (see each Capability's own Tool Affordance Contract),
never inferred here via keyword/cue matching on the question text
itself (a rejected pattern in this codebase -- see
`docs/architecture` project decisions on `TaskCategory` inference).
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, frame_io, motion, scene_detection
from .config import VideoToolConfig
from .driver_common import require_path, sample_and_decode
from .exceptions import VideoReadError
from .sampling import SamplingRequest


def _frame_timestamps_note(frames) -> str:
    stamps = ", ".join(f"{frame.timestamp_seconds:.1f}s" for frame in frames)
    return f"The following {len(frames)} frames were sampled from the video, in order, at: {stamps}."


def _maybe_ocr_note(brain: Brain, frames, *, include_ocr: bool, execution_requirements) -> str:
    if not include_ocr or not frames:
        return ""

    seen: set[str] = set()
    lines: list[str] = []

    for frame in frames:
        image_base64 = frame_io.encode_frame_base64(frame.image)
        text = engine.extract_text_from_frame(
            brain, image_base64, execution_requirements=execution_requirements
        ).strip()

        if text and text not in seen:
            seen.add(text)
            lines.append(f"[{frame.timestamp_seconds:.1f}s] {text}")

    if not lines:
        return "No visible text was detected in the sampled frames."

    return "Visible text detected in sampled frames:\n" + "\n".join(lines)


@dataclass(frozen=True, slots=True, kw_only=True)
class VideoUnderstandingSpec:
    """Immutable per-Capability configuration for `VideoUnderstandingToolDriver`."""

    provider_capability_id: str
    default_instruction: str
    question_argument: bool = False
    frame_count_attribute: str = "describe_frame_count"


class VideoUnderstandingToolDriver:
    """
    Shared `ToolDriver` for `video.describe_video`,
    `video.summarize_video`, and `video.answer_question` -- each
    differs only by its default instruction/frame budget/whether it
    requires a `question` argument, exactly like Vision's own
    `VisionToolDriver` is shared across `vision.describe_image`/
    `vision.answer_question`/... (see `vision/driver.py`'s own
    docstring for the precedent).
    """

    def __init__(
        self,
        *,
        brain: Brain,
        spec: VideoUnderstandingSpec,
        config: VideoToolConfig,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._brain = brain
        self._spec = spec
        self._config = config
        self._progress = progress_reporter or NullProgressReporter(spec.provider_capability_id)

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        instruction = self._resolve_instruction(request)
        include_ocr = bool(request.arguments.get("include_ocr", False))
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Sampling frames...")

        sampling_request = self._sampling_request(request)
        default_max_frames = getattr(self._config, self._spec.frame_count_attribute)

        sampled = sample_and_decode(
            self._brain,
            path,
            sampling_request,
            default_max_frames=default_max_frames,
            hard_cap=self._config.max_sample_frames,
        )

        if not sampled.frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Preparing context...")

        ocr_note = _maybe_ocr_note(
            self._brain,
            sampled.frames,
            include_ocr=include_ocr,
            execution_requirements=execution_requirements,
        )
        timestamps_note = _frame_timestamps_note(sampled.frames)

        final_instruction = "\n\n".join(
            part for part in (instruction, timestamps_note, ocr_note) if part
        )

        frames_base64 = tuple(
            frame_io.encode_frame_base64(frame.image) for frame in sampled.frames
        )

        self._progress.progress(message="Waiting for Video model...")

        text = engine.analyze_frames_with_provider(
            self._brain,
            self._spec.provider_capability_id,
            frames_base64,
            final_instruction,
            execution_requirements=execution_requirements,
        )

        self._progress.completed(message="Completed.")

        return ToolResponse(
            result={
                "text": text,
                "frames_analyzed": [
                    {"frame_index": frame.index, "timestamp_seconds": frame.timestamp_seconds}
                    for frame in sampled.frames
                ],
            },
            attributes={"path": path},
        )

    def _resolve_instruction(self, request: ToolRequest) -> str:
        if self._spec.question_argument:
            question = str(request.arguments.get("question", "")).strip()

            if not question:
                raise VideoReadError(
                    "request.arguments['question'] must be a non-empty string."
                )

            return question

        return (
            str(request.arguments.get("instruction", "")).strip()
            or self._spec.default_instruction
        )

    def _sampling_request(self, request: ToolRequest) -> SamplingRequest:
        focus_timestamp = request.arguments.get("timestamp_seconds")

        if focus_timestamp is not None:
            return SamplingRequest(
                focus_timestamp_seconds=float(focus_timestamp),
                focus_window_seconds=float(
                    request.arguments.get(
                        "focus_window_seconds", self._config.focus_window_seconds
                    )
                ),
                max_frames=request.arguments.get("max_frames"),
            )

        return SamplingRequest(max_frames=request.arguments.get("max_frames"))


class VideoClassifyToolDriver:
    """
    `ToolDriver` implementing `video.classify_video`: always computes
    a deterministic coarse category from metadata/motion/scene-change
    statistics first (zero model calls); escalates to the
    `video.provider_classify_video` Capability only when the caller
    supplies `candidate_labels` (open-set semantic classification, the
    exact same "provider only for open-set labels" shape
    `vision.classify_image` already establishes).
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
        self._progress = progress_reporter or NullProgressReporter("video.classify_video")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        candidate_labels = request.arguments.get("candidate_labels")
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Sampling frames...")

        sampled = sample_and_decode(
            self._brain,
            path,
            SamplingRequest(max_frames=self._config.classify_frame_count),
            default_max_frames=self._config.classify_frame_count,
            hard_cap=self._config.max_sample_frames,
        )

        if not sampled.frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Computing deterministic signals...")

        change_scores = scene_detection.compute_change_scores(sampled.frames)
        scene_change_count = sum(
            1 for sample in change_scores if sample.change_score >= self._config.scene_change_threshold
        )
        motion_scores = [
            motion.detect_motion(previous.image, current.image).changed_pixel_ratio
            for previous, current in zip(sampled.frames, sampled.frames[1:])
        ]
        average_motion = round(sum(motion_scores) / len(motion_scores), 4) if motion_scores else 0.0

        deterministic_category = self._deterministic_category(scene_change_count, average_motion)

        result: dict = {
            "deterministic_category": deterministic_category,
            "scene_change_count": scene_change_count,
            "average_motion_ratio": average_motion,
        }

        if candidate_labels:
            self._progress.progress(message="Waiting for Video model...")

            instruction = (
                "Classify this video into exactly one of the following "
                f"categories: {', '.join(str(label) for label in candidate_labels)}. "
                "Respond with the single best-matching category name."
            )
            frames_base64 = tuple(
                frame_io.encode_frame_base64(frame.image) for frame in sampled.frames
            )
            result["semantic_label"] = engine.analyze_frames_with_provider(
                self._brain,
                self._provider_capability_id,
                frames_base64,
                instruction,
                execution_requirements=execution_requirements,
            ).strip()

        self._progress.completed(message="Completed.")

        return ToolResponse(result=result, attributes={"path": path})

    @staticmethod
    def _deterministic_category(scene_change_count: int, average_motion: float) -> str:
        if scene_change_count == 0 and average_motion < 0.01:
            return "static_or_slideshow"

        if scene_change_count >= 3 or average_motion >= 0.08:
            return "dynamic_high_activity"

        return "moderate_activity"
