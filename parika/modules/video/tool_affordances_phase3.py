"""
PARIKA Video Module - Tool Affordance Contracts, Phase 3 (Timeline Understanding)

`video.generate_timeline`, `video.detect_scene_changes`,
`video.detect_shots`, `video.segment_video`, `video.detect_key_moments`.
"""

from __future__ import annotations

from typing import Any, Mapping

from .tool_affordances_phase1 import PATH_PROPERTY

_THRESHOLD_PROPERTY: Mapping[str, Any] = {
    "type": "number",
    "description": "Change-score threshold (0-1) above which two frames are considered a boundary. Optional.",
}

VIDEO_GENERATE_TIMELINE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Builds a structured timeline of a video's key moments, with timestamps, observations, and optionally visible text.",
    "use_when": 'the user wants a chronological breakdown of a video\'s events (e.g. "give me a timeline of this video").',
    "avoid_when": "the user wants a single overall description -- use `video_describe_video` instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns an ordered list of timeline entries. Present it as a chronological list.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "max_entries": {"type": "integer", "description": "Upper bound on timeline entries. Optional."},
            "include_descriptions": {"type": "boolean", "description": "Whether to narrate each entry with a Vision model. Defaults to true."},
            "include_text": {"type": "boolean", "description": "Whether to extract visible text at each entry. Defaults to false."},
        },
        "required": ["path"],
    },
}

VIDEO_DETECT_SCENE_CHANGES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically detects abrupt visual scene changes in a video.",
    "use_when": 'the user wants to know where a video\'s scenes change (e.g. "when do the scenes change in this video").',
    "avoid_when": "finer shot-level boundaries are needed -- use `video_detect_shots`.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns a list of scene-change timestamps with change scores. Present them as a list.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": PATH_PROPERTY, "threshold": _THRESHOLD_PROPERTY},
        "required": ["path"],
    },
}

VIDEO_DETECT_SHOTS_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically detects shot boundaries (cuts) in a video, at finer temporal granularity than scene changes.",
    "use_when": 'the user wants precise cut/shot boundaries (e.g. for editing or chaptering).',
    "avoid_when": "a coarser overview suffices -- use `video_detect_scene_changes`.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns a list of shot-boundary timestamps with change scores. Present them as a list.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": PATH_PROPERTY, "threshold": _THRESHOLD_PROPERTY},
        "required": ["path"],
    },
}

VIDEO_SEGMENT_VIDEO_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Splits a video into contiguous temporal segments at detected shot boundaries.",
    "use_when": 'the user wants a video divided into chapters/segments (e.g. "split this video into segments").',
    "avoid_when": "only the boundary timestamps are needed -- use `video_detect_shots` instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns an ordered list of segments with start/end timestamps. Present them as a list.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": PATH_PROPERTY, "threshold": _THRESHOLD_PROPERTY},
        "required": ["path"],
    },
}

VIDEO_DETECT_KEY_MOMENTS_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Identifies the video's most visually significant moments (largest visual changes), optionally explained by a video-capable model.",
    "use_when": 'the user wants the "highlights" or most important moments of a video.',
    "avoid_when": "a full chronological breakdown is wanted instead -- use `video_generate_timeline`.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns a ranked-then-chronological list of candidate key moments, with an explanation when requested. Present as a list.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "max_moments": {"type": "integer", "description": "Upper bound on returned moments. Optional."},
            "include_explanation": {"type": "boolean", "description": "Whether to ask a video-capable model to explain the candidates. Defaults to false."},
        },
        "required": ["path"],
    },
}
