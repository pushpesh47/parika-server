"""
PARIKA Video Module - Video Comparison Driver

`video.compare_videos`. Deterministic by default (metadata, sampled-
frame visual similarity, scene-structure counts); reuses Vision's own
`vision.provider_compare_images` Capability -- the same one
`vision.compare_images` itself escalates to -- only when the caller
explicitly opts into `include_semantic_diff`, comparing one
representative frame from each video rather than every frame.
"""

from __future__ import annotations

from parika.core.brain.brain import Brain
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter

from . import engine, frame_io, hashing, metadata_probe, scene_detection
from .config import VideoToolConfig
from .driver_common import probe_properties, require_path
from .exceptions import VideoReadError
from .sampling import uniform_indices

_DEFAULT_COMPARISON_FRAME_COUNT = 5


class VideoCompareVideosToolDriver:
    """`ToolDriver` implementing `video.compare_videos`."""

    def __init__(self, *, brain: Brain, config: VideoToolConfig, progress_reporter: ProgressReporter | None = None) -> None:
        self._brain = brain
        self._config = config
        self._progress = progress_reporter or NullProgressReporter("video.compare_videos")

    def execute(self, request: ToolRequest) -> ToolResponse:
        path_a = require_path(request)
        path_b = str(request.arguments.get("path_b", "")).strip()

        if not path_b:
            raise VideoReadError("request.arguments['path_b'] must be a non-empty string.")

        include_semantic_diff = bool(request.arguments.get("include_semantic_diff", False))
        execution_requirements = request.metadata.get("execution_requirements")

        self._progress.started(message="Probing both videos...")

        resolved_a = engine.resolve_video_path(self._brain, path_a)
        resolved_b = engine.resolve_video_path(self._brain, path_b)
        metadata_a = metadata_probe.probe_container_properties(resolved_a)
        metadata_b = metadata_probe.probe_container_properties(resolved_b)

        self._progress.progress(message="Sampling frames from both videos...")

        frames_a = self._sample(resolved_a)
        frames_b = self._sample(resolved_b)

        self._progress.progress(message="Comparing sampled frames...")

        pair_count = min(len(frames_a), len(frames_b))
        pixel_similarities = [
            hashing.pixel_similarity(frames_a[index].image, frames_b[index].image)
            for index in range(pair_count)
        ]
        visual_similarity = (
            round(sum(pixel_similarities) / len(pixel_similarities), 4) if pixel_similarities else None
        )

        scene_changes_a = len(
            scene_detection.detect_boundaries(frames_a, threshold=self._config.scene_change_threshold)
        ) if len(frames_a) > 1 else 0
        scene_changes_b = len(
            scene_detection.detect_boundaries(frames_b, threshold=self._config.scene_change_threshold)
        ) if len(frames_b) > 1 else 0

        result: dict = {
            "metadata_a": metadata_a.to_result_dict(),
            "metadata_b": metadata_b.to_result_dict(),
            "duration_difference_seconds": (
                round(abs((metadata_a.duration_seconds or 0) - (metadata_b.duration_seconds or 0)), 3)
                if metadata_a.duration_seconds is not None and metadata_b.duration_seconds is not None
                else None
            ),
            "same_resolution": (metadata_a.width, metadata_a.height) == (metadata_b.width, metadata_b.height),
            "same_frame_rate": metadata_a.frame_rate == metadata_b.frame_rate,
            "visual_similarity": visual_similarity,
            "scene_change_count_a": scene_changes_a,
            "scene_change_count_b": scene_changes_b,
        }

        if include_semantic_diff and frames_a and frames_b:
            self._progress.progress(message="Waiting for Vision model...")

            mid_a = frames_a[len(frames_a) // 2]
            mid_b = frames_b[len(frames_b) // 2]
            result["semantic_difference"] = engine.analyze_frames_with_provider(
                self._brain,
                engine.VISION_PROVIDER_COMPARE_IMAGES_CAPABILITY_ID,
                (
                    frame_io.encode_frame_base64(mid_a.image),
                    frame_io.encode_frame_base64(mid_b.image),
                ),
                "Compare these two representative video frames (one from "
                "each video) and describe the key visual differences.",
                execution_requirements=execution_requirements,
            )

        self._progress.completed(message="Completed.")

        return ToolResponse(result=result, attributes={"path_a": path_a, "path_b": path_b})

    def _sample(self, resolved_path: str):
        properties = probe_properties(resolved_path)
        indices = uniform_indices(
            frame_count=properties.frame_count, max_frames=_DEFAULT_COMPARISON_FRAME_COUNT
        )
        return frame_io.extract_frames(resolved_path, indices, frame_rate=properties.frame_rate)
