"""
PARIKA Video Module - Document/Slide Understanding Drivers

`video.detect_documents`, `video.detect_slides`, `video.extract_tables`.
Reuses OCR's own `ocr.provider_extract_text` Capability
(`engine.extract_text_from_frame()`) for text-density signals and
deterministic shot-boundary/change-score detection
(`scene_detection.py`/`hashing.py`) for static-segment detection --
never a second OCR or table-recognition engine.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, frame_io, hashing
from .config import VideoToolConfig
from .driver_common import probe_properties, require_path
from .exceptions import VideoReadError
from .sampling import dense_indices, uniform_indices

_MIN_DOCUMENT_TEXT_LENGTH = 40
_STATIC_CHANGE_SCORE_THRESHOLD = 0.08


def _looks_tabular(text: str) -> bool:
    """
    Deterministic, structural heuristic (never a keyword/intent
    match): at least three consecutive non-empty lines each
    containing two or more multi-space-separated columns suggest a
    tabular layout -- the same "structure, not content" signal
    `ocr/table_detection.py` uses at the pixel level, applied here to
    already-extracted text.
    """

    consecutive = 0

    for line in text.splitlines():
        columns = [column for column in line.split("  ") if column.strip()]
        if len(columns) >= 2:
            consecutive += 1
            if consecutive >= 3:
                return True
        else:
            consecutive = 0

    return False


class VideoDetectDocumentsToolDriver:
    """
    `ToolDriver` implementing `video.detect_documents`: samples frames
    and flags any whose extracted text (`engine.extract_text_from_frame()`)
    exceeds a minimum length as document-like.
    """

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_documents")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        min_text_length = int(request.arguments.get("min_text_length", _MIN_DOCUMENT_TEXT_LENGTH))
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Sampling frames...")

        resolved_path = engine.resolve_video_path(self._brain, path)
        properties = probe_properties(resolved_path)
        indices = uniform_indices(
            frame_count=properties.frame_count, max_frames=self._config.describe_frame_count
        )
        frames = frame_io.extract_frames(resolved_path, indices, frame_rate=properties.frame_rate)

        if not frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Extracting text from sampled frames...")

        document_frames = []
        for frame in frames:
            image_base64 = frame_io.encode_frame_base64(frame.image)
            text = engine.extract_text_from_frame(
                self._brain, image_base64, execution_requirements=execution_requirements
            ).strip()

            if len(text) >= min_text_length:
                document_frames.append(
                    {
                        "frame_index": frame.index,
                        "timestamp_seconds": frame.timestamp_seconds,
                        "text_length": len(text),
                    }
                )

        self._progress.completed(message="Completed.")

        return ToolResponse(result={"document_frames": document_frames}, attributes={"path": path})


class VideoDetectSlidesToolDriver:
    """
    `ToolDriver` implementing `video.detect_slides`: dense-samples the
    video and groups consecutive near-identical frames
    (`hashing.change_score()` below a static threshold) into
    candidate slide segments of at least `min_duration_seconds` --
    deterministic visual-similarity + temporal segmentation, never a
    model call.
    """

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.detect_slides")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        min_duration = float(
            request.arguments.get("min_duration_seconds", self._config.min_slide_duration_seconds)
        )

        self._progress.started(message="Sampling frames...")

        resolved_path = engine.resolve_video_path(self._brain, path)
        properties = probe_properties(resolved_path)
        indices = dense_indices(
            frame_count=properties.frame_count,
            frame_rate=properties.frame_rate,
            target_fps=self._config.dense_sample_target_fps,
            max_frames=self._config.max_sample_frames,
        )
        frames = frame_io.extract_frames(resolved_path, indices, frame_rate=properties.frame_rate)

        if len(frames) < 2:
            self._progress.completed(message="Completed.")
            return ToolResponse(result={"slide_segments": []}, attributes={"path": path})

        self._progress.progress(message="Grouping static segments...")

        segments: list[dict] = []
        segment_start = frames[0]
        previous = frames[0]

        for current in frames[1:]:
            score = hashing.change_score(previous.image, current.image)

            if score.overall >= _STATIC_CHANGE_SCORE_THRESHOLD:
                duration = previous.timestamp_seconds - segment_start.timestamp_seconds
                if duration >= min_duration:
                    segments.append(
                        {
                            "start_seconds": segment_start.timestamp_seconds,
                            "end_seconds": previous.timestamp_seconds,
                            "start_frame_index": segment_start.index,
                            "end_frame_index": previous.index,
                        }
                    )
                segment_start = current

            previous = current

        final_duration = previous.timestamp_seconds - segment_start.timestamp_seconds
        if final_duration >= min_duration:
            segments.append(
                {
                    "start_seconds": segment_start.timestamp_seconds,
                    "end_seconds": previous.timestamp_seconds,
                    "start_frame_index": segment_start.index,
                    "end_frame_index": previous.index,
                }
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(result={"slide_segments": segments}, attributes={"path": path})


class VideoExtractTablesToolDriver:
    """
    `ToolDriver` implementing `video.extract_tables`: identifies
    candidate frames (an explicit `frame_indices`/`timestamps_seconds`
    override, or else this Module's own deterministic sampling),
    extracts raw text via `engine.extract_text_from_frame()` (OCR's
    own Capability, reused), and flags text that structurally looks
    tabular (`_looks_tabular()`). This Capability deliberately does
    NOT implement cell-grid table parsing itself -- that already
    exists in `ocr.extract_table`/`document.extract_tables`, which
    operate on a file path rather than an in-memory frame; a caller
    needing fully structured cells should export the flagged frame
    (`video.extract_frames` with `include_image_data=true`) and pass
    it to one of those existing Capabilities directly.
    """

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.extract_tables")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Sampling candidate frames...")

        resolved_path = engine.resolve_video_path(self._brain, path)
        properties = probe_properties(resolved_path)

        frame_indices = request.arguments.get("frame_indices")
        if frame_indices:
            indices = sorted({int(index) for index in frame_indices})
        else:
            indices = uniform_indices(
                frame_count=properties.frame_count, max_frames=self._config.describe_frame_count
            )

        frames = frame_io.extract_frames(resolved_path, indices, frame_rate=properties.frame_rate)

        if not frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Extracting text from candidate frames...")

        candidates = []
        for frame in frames:
            image_base64 = frame_io.encode_frame_base64(frame.image)
            text = engine.extract_text_from_frame(
                self._brain, image_base64, execution_requirements=execution_requirements
            ).strip()

            if not text:
                continue

            candidates.append(
                {
                    "frame_index": frame.index,
                    "timestamp_seconds": frame.timestamp_seconds,
                    "likely_contains_table": _looks_tabular(text),
                    "raw_text": text,
                }
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(result={"candidates": candidates}, attributes={"path": path})
