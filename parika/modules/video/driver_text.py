"""
PARIKA Video Module - Text Understanding Driver

`video.extract_text`. Reuses OCR's own `ocr.provider_extract_text`
Capability directly (`engine.extract_text_from_frame()`) -- never a
second OCR implementation. Two deterministic-first cost controls,
both applied before any model call:

1. Frames that are visually near-identical to the previous *sampled*
   frame (`hashing.change_score()` below a low threshold) are skipped
   entirely -- OCR is never re-run on a frame that almost certainly
   shows the same text as the one just processed.
2. Consecutive OCR results with identical text are collapsed into one
   entry spanning both timestamps, rather than repeating the same
   string once per sampled frame.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, frame_io, hashing
from .config import VideoToolConfig
from .driver_common import probe_properties, require_path, sampling_request_from_arguments
from .exceptions import VideoReadError
from .sampling import interval_indices, resolve_indices

_DEFAULT_OCR_INTERVAL_SECONDS = 2.0
_UNCHANGED_FRAME_SCORE_THRESHOLD = 0.05


class VideoExtractTextToolDriver:
    """`ToolDriver` implementing `video.extract_text`."""

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.extract_text")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path = require_path(request)
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Sampling frames...")

        resolved_path = engine.resolve_video_path(self._brain, path)
        properties = probe_properties(resolved_path)
        sampling_request = sampling_request_from_arguments(request)

        if sampling_request.frame_indices or sampling_request.timestamps_seconds:
            indices = resolve_indices(
                sampling_request,
                frame_count=properties.frame_count,
                frame_rate=properties.frame_rate,
                default_max_frames=self._config.max_sample_frames,
                hard_cap=self._config.max_sample_frames,
            )
        else:
            interval_seconds = float(
                request.arguments.get("interval_seconds", _DEFAULT_OCR_INTERVAL_SECONDS)
            )
            indices = interval_indices(
                frame_count=properties.frame_count,
                frame_rate=properties.frame_rate,
                interval_seconds=interval_seconds,
            )[: self._config.max_sample_frames]

        frames = frame_io.extract_frames(resolved_path, indices, frame_rate=properties.frame_rate)

        if not frames:
            raise VideoReadError(f"No frames could be sampled from '{path}'.")

        self._progress.progress(message="Extracting text from sampled frames...")

        raw_entries: list[dict] = []
        previous_frame = None

        for frame in frames:
            if previous_frame is not None:
                score = hashing.change_score(previous_frame.image, frame.image)
                if score.overall < _UNCHANGED_FRAME_SCORE_THRESHOLD:
                    continue

            image_base64 = frame_io.encode_frame_base64(frame.image)
            text = engine.extract_text_from_frame(
                self._brain, image_base64, execution_requirements=execution_requirements
            ).strip()

            raw_entries.append(
                {"timestamp_seconds": frame.timestamp_seconds, "frame_index": frame.index, "text": text}
            )
            previous_frame = frame

        deduplicated: list[dict] = []
        for entry in raw_entries:
            if deduplicated and deduplicated[-1]["text"] == entry["text"]:
                deduplicated[-1]["end_timestamp_seconds"] = entry["timestamp_seconds"]
                continue

            deduplicated.append(
                {
                    "timestamp_seconds": entry["timestamp_seconds"],
                    "end_timestamp_seconds": entry["timestamp_seconds"],
                    "frame_index": entry["frame_index"],
                    "text": entry["text"],
                }
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(result={"text_segments": deduplicated}, attributes={"path": path})
