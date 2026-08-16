"""
PARIKA Video Module - Tool Affordance Contracts, Phase 5
(Events/Actions, Text, Documents/Slides, Comparison, Quality)

`video.detect_events`, `video.detect_actions`, `video.extract_text`,
`video.detect_documents`, `video.detect_slides`, `video.extract_tables`,
`video.compare_videos`, `video.detect_blur`, `video.detect_black_frames`,
`video.detect_rotation`, `video.detect_corruption`.
"""

from __future__ import annotations

from typing import Any, Mapping

from .tool_affordances_phase1 import PATH_PROPERTY

VIDEO_DETECT_EVENTS_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically detects candidate events over time: scene changes, motion spikes, and black-frame transitions.",
    "use_when": 'the user wants to know what notable things happen and when in a video.',
    "avoid_when": "recognizable actions/activities are wanted instead -- use `video_detect_actions`.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns a chronological list of typed events with timestamps. Present it as a list.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "max_events": {"type": "integer", "description": "Upper bound on returned events. Optional."},
        },
        "required": ["path"],
    },
}

VIDEO_DETECT_ACTIONS_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Recognizes actions/activities across sampled video frames using a video-capable model, with a confidence estimate.",
    "use_when": 'the user wants to know what action/activity is taking place in a video.',
    "avoid_when": "only visual-change timing is needed -- use `video_detect_motion`/`video_detect_events` instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns a free-text action description and a `confidence` derived from the underlying motion level. Present both, noting low confidence honestly.",
    "failure_semantics": "If the video cannot be read or no video-capable model is available, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": PATH_PROPERTY},
        "required": ["path"],
    },
}

VIDEO_EXTRACT_TEXT_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Extracts visible on-screen text from a video's frames over time, deduplicating repeated/unchanged text.",
    "use_when": 'the user wants text that appears in a video (captions, on-screen labels, slides) extracted.',
    "avoid_when": "the text is in a static image/document file -- use OCR's `ocr_extract_text` instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns a chronological list of text segments with timestamp ranges. Present it as a timeline of text.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "interval_seconds": {"type": "number", "description": "Sampling interval in seconds. Optional."},
        },
        "required": ["path"],
    },
}

VIDEO_DETECT_DOCUMENTS_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Flags video frames that appear to contain substantial document-like text.",
    "use_when": 'the user wants to know if/when a video shows a document.',
    "avoid_when": "a static image/document file is being analyzed instead -- use Document's/OCR's own Capabilities.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns flagged frames with text length. Present a summary.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "min_text_length": {"type": "integer", "description": "Minimum extracted text length to flag a frame. Optional."},
        },
        "required": ["path"],
    },
}

VIDEO_DETECT_SLIDES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Detects presentation/slideshow segments: spans of near-static, visually-similar consecutive frames.",
    "use_when": 'the user wants to know which parts of a video are a slideshow/presentation.',
    "avoid_when": "abrupt scene changes are wanted instead -- use `video_detect_scene_changes`.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns a list of candidate slide segments with start/end timestamps. Present it as a list.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "min_duration_seconds": {"type": "number", "description": "Minimum static-segment duration to count as a slide. Optional."},
        },
        "required": ["path"],
    },
}

VIDEO_EXTRACT_TABLES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Identifies candidate video frames likely containing a visible table and extracts their raw OCR text.",
    "use_when": 'the user wants tabular data visible in a video read.',
    "avoid_when": "the table is in a static document/image file -- use `document_extract_tables`/`ocr_extract_table` for fully structured cell extraction instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns raw text per candidate frame with a `likely_contains_table` flag -- not fully structured cells. Explain this limitation if the user expects a structured table.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "frame_indices": {"type": "array", "items": {"type": "integer"}, "description": "Explicit candidate frame indices. Optional."},
        },
        "required": ["path"],
    },
}

VIDEO_COMPARE_VIDEOS_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Compares two videos: duration, resolution, frame rate, sampled-frame visual similarity, and scene-structure counts; optionally a semantic difference via a Vision model.",
    "use_when": 'the user wants two videos compared.',
    "avoid_when": "comparing two specific frames instead -- use `video_compare_frames`.",
    "requires": "both video file paths; ask the user for either if not already known.",
    "result_semantics": "Returns deterministic comparison metrics, plus a semantic difference only when `include_semantic_diff` was set. Present the relevant differences.",
    "failure_semantics": "If either video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "path_b": {"type": "string", "description": "The second video's file path."},
            "include_semantic_diff": {"type": "boolean", "description": "Whether to ask a Vision model to describe semantic differences. Defaults to false."},
        },
        "required": ["path", "path_b"],
    },
}

VIDEO_DETECT_BLUR_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically measures sharpness (variance of Laplacian) across a video's sampled frames.",
    "use_when": 'the user wants to know if a video is blurry/out of focus.',
    "avoid_when": "a single image is being analyzed instead -- use Vision's `vision_detect_blur`.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns per-frame sharpness and an overall blurry-frame ratio. Present a summary.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": PATH_PROPERTY, "threshold": {"type": "number", "description": "Blur variance cutoff. Optional."}},
        "required": ["path"],
    },
}

VIDEO_DETECT_BLACK_FRAMES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically detects black/near-black frames (e.g. fade transitions, dropped frames).",
    "use_when": 'the user wants to find black frames or fade-to-black transitions in a video.',
    "avoid_when": "general motion/scene analysis is wanted instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns flagged black frames with timestamps. Present a summary.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": PATH_PROPERTY, "threshold": {"type": "number", "description": "Mean-brightness cutoff. Optional."}},
        "required": ["path"],
    },
}

VIDEO_DETECT_ROTATION_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically estimates whether a video's frames are unexpectedly rotated.",
    "use_when": 'the user asks whether a video is sideways/upside down.',
    "avoid_when": "a single image is being analyzed instead -- use Vision's `vision_detect_rotation`.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns the majority-vote rotation estimate and confidence. Present it plainly.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": PATH_PROPERTY},
        "required": ["path"],
    },
}

VIDEO_DETECT_CORRUPTION_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Deterministically checks whether a video's container or a probe set of its frames are unreadable/corrupt.",
    "use_when": 'the user suspects a video file is broken/corrupted.',
    "avoid_when": "general quality (blur/black frames) is wanted instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns whether the video is considered corrupted and why. Present it plainly.",
    "failure_semantics": "This Capability itself reports corruption as a result rather than raising, except for permission/path errors, which should be explained in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": PATH_PROPERTY},
        "required": ["path"],
    },
}
