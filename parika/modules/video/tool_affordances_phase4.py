"""
PARIKA Video Module - Tool Affordance Contracts, Phase 4 (Objects & Motion)

`video.detect_objects`, `video.count_objects`, `video.track_objects`,
`video.detect_motion`, `video.compare_frames`.
"""

from __future__ import annotations

from typing import Any, Mapping

from .tool_affordances_phase1 import PATH_PROPERTY, SAMPLING_PROPERTIES

VIDEO_DETECT_OBJECTS_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Detects objects across sampled frames of a video, preserving each detection's timestamp.",
    "use_when": 'the user wants objects found across a video (e.g. "find every car in this video").',
    "avoid_when": "a single image is being analyzed instead -- use Vision's `vision_detect_objects`.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns per-sampled-frame detections with timestamps. Present them naturally.",
    "failure_semantics": "If the video cannot be read or no Vision-capable model is available, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "instruction": {"type": "string", "description": "Which object(s) to detect. Optional."},
            **SAMPLING_PROPERTIES,
        },
        "required": ["path"],
    },
}

VIDEO_COUNT_OBJECTS_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Counts objects in a video: deterministic per-frame moving-region counts by default, or a named object's count via a Vision model when requested.",
    "use_when": 'the user wants an object count in a video (e.g. "how many people appear in this video").',
    "avoid_when": "a single image is being analyzed instead -- use Vision's `vision_count_objects`.",
    "requires": "the video file path; ask the user for it if not already known. Optionally, a specific object name.",
    "result_semantics": "Returns per-frame counts and a frame-level maximum; never a unique-object claim unless explicitly noted as such. Present the relevant numbers plainly.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "candidate_object": {"type": "string", "description": "A specific object name to count via a Vision model. Optional."},
            **SAMPLING_PROPERTIES,
        },
        "required": ["path"],
    },
}

VIDEO_TRACK_OBJECTS_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Attempts to track objects across a video's frames; falls back to frame-level detection (no identity linking) when a robust tracker is unavailable.",
    "use_when": 'the user wants to know how an object moves/persists across a video.',
    "avoid_when": "a simple per-frame object list suffices -- use `video_detect_objects` instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns `tracking_available` (usually false in this environment) plus per-frame detections. Be explicit that identities are not linked across frames when `tracking_available` is false.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "instruction": {"type": "string", "description": "Which object(s) to detect. Optional."},
        },
        "required": ["path"],
    },
}

VIDEO_DETECT_MOTION_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically detects meaningful motion between consecutive sampled frames.",
    "use_when": 'the user wants to know where/when motion occurs in a video.',
    "avoid_when": "semantic action recognition is wanted instead -- use `video_detect_actions`.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns per-transition changed-pixel ratios and candidate motion regions. Present a summary.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "pixel_threshold": {"type": "integer", "description": "Per-pixel intensity delta threshold. Optional."},
            "area_ratio_threshold": {"type": "number", "description": "Changed-pixel ratio required to flag motion. Optional."},
            **SAMPLING_PROPERTIES,
        },
        "required": ["path"],
    },
}

VIDEO_COMPARE_FRAMES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Compares two specific frames (from the same or two different videos) for visual/structural similarity and changed regions.",
    "use_when": 'the user wants two specific moments (or two videos) compared frame-by-frame.',
    "avoid_when": "an overall video-to-video comparison is wanted instead -- use `video_compare_videos`.",
    "requires": "the primary video path, plus a way to identify each frame (`frame_index_a`/`timestamp_a` and `frame_index_b`/`timestamp_b`); `path_b` only if comparing a frame from a different video.",
    "result_semantics": "Returns similarity scores and changed regions. Present them naturally.",
    "failure_semantics": "If either frame cannot be decoded, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "path_b": {"type": "string", "description": "A second video's path, if comparing across videos. Optional."},
            "frame_index_a": {"type": "integer", "description": "First frame's index. Optional."},
            "timestamp_a": {"type": "number", "description": "First frame's timestamp (seconds). Optional."},
            "frame_index_b": {"type": "integer", "description": "Second frame's index. Optional."},
            "timestamp_b": {"type": "number", "description": "Second frame's timestamp (seconds). Optional."},
        },
        "required": ["path"],
    },
}
