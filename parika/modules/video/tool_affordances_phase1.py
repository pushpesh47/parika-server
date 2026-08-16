"""
PARIKA Video Module - Tool Affordance Contracts, Phase 1 (I/O)

`video.read_video`, `video.extract_metadata`, `video.extract_frames`,
`video.extract_keyframes`, `video.extract_thumbnails`. Split out of
`module_driver.py` purely to keep that file within the project's File
Size Guidelines, exactly like `parika/modules/vision/tool_affordances_phase1.py`.
"""

from __future__ import annotations

from typing import Any, Mapping

PATH_PROPERTY: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the video file.",
}

SAMPLING_PROPERTIES: Mapping[str, Any] = {
    "frame_indices": {
        "type": "array",
        "items": {"type": "integer"},
        "description": "Explicit frame indices to use instead of automatic sampling.",
    },
    "timestamps_seconds": {
        "type": "array",
        "items": {"type": "number"},
        "description": "Explicit timestamps (seconds) to use instead of automatic sampling.",
    },
    "interval_seconds": {
        "type": "number",
        "description": "Sample one frame every this many seconds instead of automatic sampling.",
    },
    "max_frames": {
        "type": "integer",
        "description": "Upper bound on the number of frames sampled/returned.",
    },
}

VIDEO_READ_VIDEO_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Validates a local video file and reports its basic, cheaply-probed properties.",
    "use_when": "the user references a local video file and you need to confirm it is readable before doing anything else with it.",
    "avoid_when": "full metadata (codec/bitrate/audio) is needed -- use `video_extract_metadata` instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns basic properties (dimensions, frame rate, frame count, container format). Present relevant fields naturally.",
    "failure_semantics": "If the path does not exist, is not a file, or cannot be decoded, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": PATH_PROPERTY},
        "required": ["path"],
    },
}

VIDEO_EXTRACT_METADATA_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Extracts deterministic video metadata: duration, dimensions, frame rate, frame count, codec, container format, bitrate, and audio/video stream presence.",
    "use_when": "the user asks about a video's duration, resolution, frame rate, codec, or whether it has audio.",
    "avoid_when": "the user wants a description of the video's content -- use `video_describe_video` instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Summarize the relevant metadata naturally; do not dump the raw structure.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {"path": PATH_PROPERTY},
        "required": ["path"],
    },
}

VIDEO_EXTRACT_FRAMES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Extracts individual frames from a local video using deterministic sampling (indices, timestamps, interval, or an evenly-spaced default).",
    "use_when": "the user wants specific frames or a bounded set of representative frames from a video.",
    "avoid_when": "the user wants one representative frame per shot -- use `video_extract_keyframes` instead; or a single contact-sheet image -- use `video_extract_thumbnails`.",
    "requires": "the video file path; ask the user for it if not already known. Optionally, which frames/timestamps/interval to use.",
    "result_semantics": "Returns each sampled frame's index/timestamp (and base64 image data only when `include_image_data` was requested). Present a summary, not raw base64, unless the user needs the image data itself.",
    "failure_semantics": "If the video cannot be read or no frames could be decoded, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            **SAMPLING_PROPERTIES,
            "include_image_data": {
                "type": "boolean",
                "description": "Whether to include each frame's base64-encoded image data. Defaults to false.",
            },
        },
        "required": ["path"],
    },
}

VIDEO_EXTRACT_KEYFRAMES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Extracts one representative frame per detected shot -- a compact, deduplicated summary of the video's visual content.",
    "use_when": "the user wants representative frames without duplicates from similar consecutive frames.",
    "avoid_when": "the user wants every frame or specific timestamps -- use `video_extract_frames` instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns each keyframe's index/timestamp (and base64 image data only when requested). Present a summary.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "max_keyframes": {"type": "integer", "description": "Upper bound on returned keyframes."},
            "include_image_data": {
                "type": "boolean",
                "description": "Whether to include each keyframe's base64-encoded image data. Defaults to false.",
            },
        },
        "required": ["path"],
    },
}

VIDEO_EXTRACT_THUMBNAILS_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Generates a single contact-sheet image (a grid of uniformly-sampled frames) for a local video.",
    "use_when": "the user wants a quick visual overview/preview image of a video.",
    "avoid_when": "the user wants individual frame data -- use `video_extract_frames` instead.",
    "requires": "the video file path; ask the user for it if not already known.",
    "result_semantics": "Returns one base64-encoded contact-sheet image plus the frames it contains. Present it as an image, not raw base64 text.",
    "failure_semantics": "If the video cannot be read, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": PATH_PROPERTY,
            "columns": {"type": "integer", "description": "Grid columns. Optional."},
            "rows": {"type": "integer", "description": "Grid rows. Optional."},
            "cell_width": {"type": "integer", "description": "Pixel width of each grid cell. Optional."},
        },
        "required": ["path"],
    },
}
