"""
PARIKA Video Module - Tool Affordance Contracts, Phase 2 (Video Understanding)

`video.describe_video`, `video.summarize_video`, `video.answer_question`,
`video.classify_video`.
"""

from __future__ import annotations

from typing import Any, Mapping

from .tool_affordances_phase1 import PATH_PROPERTY

_INSTRUCTION_PROPERTY: Mapping[str, Any] = {
    "type": "string",
    "description": "What to focus on. Optional; defaults to a general analysis.",
}

_TIMESTAMP_FOCUS_PROPERTIES: Mapping[str, Any] = {
    "timestamp_seconds": {
        "type": "number",
        "description": "Focus sampling around this timestamp (seconds) instead of the whole video. Optional.",
    },
    "focus_window_seconds": {
        "type": "number",
        "description": "Width of the focus window around `timestamp_seconds`. Optional.",
    },
    "max_frames": {"type": "integer", "description": "Upper bound on sampled frames. Optional."},
    "include_ocr": {
        "type": "boolean",
        "description": "Whether to extract and include visible on-screen text from the sampled frames. Set this when the question concerns on-screen text.",
    },
}

VIDEO_DESCRIBE_VIDEO_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Produces a high-level description of a local video by sampling representative frames and reasoning over them with a video-capable model.",
    "use_when": 'the user wants a general description of a video (e.g. "describe this video", "what happens in this clip").',
    "avoid_when": "the user wants a concise summary of events (use `video_summarize_video`) or asks a specific question (use `video_answer_question`).",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns the description. Present it directly, in prose.",
    "failure_semantics": "If the video cannot be read or no video-capable model is available, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "instruction": _INSTRUCTION_PROPERTY,
            **_TIMESTAMP_FOCUS_PROPERTIES,
        },
        "required": ["path"],
    },
}

VIDEO_SUMMARIZE_VIDEO_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Produces a concise summary of a video's key scenes and events over time.",
    "use_when": 'the user wants a summary of a video\'s events (e.g. "summarize this video", "what are the key moments").',
    "avoid_when": "the user wants an exhaustive frame-by-frame description -- use `video_generate_timeline` instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns the summary. Present it directly, in prose.",
    "failure_semantics": "If the video cannot be read or no video-capable model is available, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "instruction": _INSTRUCTION_PROPERTY,
            **_TIMESTAMP_FOCUS_PROPERTIES,
        },
        "required": ["path"],
    },
}

VIDEO_ANSWER_QUESTION_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Answers a specific question about a local video's content, optionally focused on a specific timestamp.",
    "use_when": 'the user asks a specific question about a video (e.g. "what color is the car at 0:30?", "does anyone speak in this clip?").',
    "avoid_when": "the user wants a general description instead -- use `video_describe_video`.",
    "requires": "the video file path and the specific question; ask the user for either if not already known. If the question refers to a specific moment, pass `timestamp_seconds`.",
    "result_semantics": "Returns the answer. Present it directly, in plain language.",
    "failure_semantics": "If the video cannot be read or no video-capable model is available, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "question": {"type": "string", "description": "The specific question to answer about the video."},
            **_TIMESTAMP_FOCUS_PROPERTIES,
        },
        "required": ["path", "question"],
    },
}

VIDEO_CLASSIFY_VIDEO_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Classifies a video into a coarse deterministic activity category, or into one of a supplied set of candidate labels using a video-capable model.",
    "use_when": 'the user wants a video categorized (e.g. "is this a slideshow or an action clip", or a specific set of candidate categories).',
    "avoid_when": "the user wants a free-form description instead -- use `video_describe_video`.",
    "requires": "the video file path; ask the user for it if not already known. Optionally, candidate category labels.",
    "result_semantics": "Returns a deterministic coarse category always, plus a semantic label when candidate_labels were supplied. Present the most relevant one.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "candidate_labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Candidate category labels for semantic classification. Optional.",
            },
        },
        "required": ["path"],
    },
}
