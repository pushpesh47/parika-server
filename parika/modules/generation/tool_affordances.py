"""
PARIKA Generation Module - Tool Affordance Contracts

The Tool Affordance Contract (`metadata["tool_affordance"]`) for each
of this Module's five advertised `image.*`/`video.*` Capabilities,
consumed generically by AI Context Engineering
(`parika/interfaces/ai_context/tool_context.py`) -- exactly the same
contract shape every other Module's affordances already use.

None of these parameter schemas mention ComfyUI, a workflow, a node,
a checkpoint, or any other provider-specific concept: they describe
only the semantic generation operation, matching the architecture's
requirement that "the provider translates the semantic operation into
an appropriate workflow."
"""

from __future__ import annotations

from typing import Any, Mapping

_PROMPT_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Text description of the desired result.",
}

_NEGATIVE_PROMPT_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Optional text describing what to avoid in the result.",
}

_IMAGE_PATH_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the source image.",
}

_VIDEO_PATH_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": "Absolute or root-relative filesystem path of the source video.",
}

_WIDTH_PARAMETER: Mapping[str, Any] = {
    "type": "integer",
    "description": "Optional requested output width in pixels.",
}

_HEIGHT_PARAMETER: Mapping[str, Any] = {
    "type": "integer",
    "description": "Optional requested output height in pixels.",
}

_DURATION_PARAMETER: Mapping[str, Any] = {
    "type": "number",
    "description": "Optional requested output duration, in seconds.",
}

_SEED_PARAMETER: Mapping[str, Any] = {
    "type": "integer",
    "description": "Optional deterministic seed. Omit for a random result.",
}

_OUTPUT_PATH_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "description": (
        "Where to write the result. Optional; defaults to a "
        "generated filename in the configured output directory."
    ),
}

IMAGE_GENERATE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Generates a new image from a text description.",
    "use_when": (
        "the user wants an image created from scratch (e.g. "
        '"generate an image of...", "create a picture of...", '
        '"draw...").'
    ),
    "avoid_when": (
        "the user wants to modify an existing image (use "
        "`image_edit`), or wants an existing image described/"
        "analyzed (use Vision's `vision_describe_image`)."
    ),
    "requires": "a text description of the desired image.",
    "result_semantics": "Returns the generated image's output_path.",
    "failure_semantics": (
        "If no image-generation Provider model is currently "
        "available, explain the problem in plain language without "
        "exposing internal exception details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": _PROMPT_PARAMETER,
            "negative_prompt": _NEGATIVE_PROMPT_PARAMETER,
            "width": _WIDTH_PARAMETER,
            "height": _HEIGHT_PARAMETER,
            "seed": _SEED_PARAMETER,
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["prompt"],
    },
}

IMAGE_EDIT_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Edits an existing local image according to a text "
        "instruction (e.g. removing/changing content, restyling, "
        "restoring/enhancing)."
    ),
    "use_when": (
        'the user wants an existing image changed (e.g. "remove the '
        'people from this image", "change the sky to a sunset", '
        '"make this look like an oil painting", "restore and '
        'enhance this old photograph").'
    ),
    "avoid_when": (
        "the user wants a brand new image instead (use "
        "`image_generate`), or wants deterministic cropping/resizing/"
        "rotation/format conversion/compression (use Vision's own "
        "`vision_crop_image`/`vision_resize_image`/etc.), or wants "
        "deterministic background removal/sharpening (use Vision's "
        "`vision_remove_background`/`vision_enhance_image`)."
    ),
    "requires": (
        "the source image file path and a text instruction describing "
        "the desired change; ask the user for either if not already "
        "known."
    ),
    "result_semantics": "Returns the edited image's output_path.",
    "failure_semantics": (
        "If the image cannot be read or no image-generation Provider "
        "model is currently available, explain the problem in plain "
        "language without exposing internal exception details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _IMAGE_PATH_PARAMETER,
            "prompt": {
                "type": "string",
                "description": "The desired change, as a text instruction.",
            },
            "negative_prompt": _NEGATIVE_PROMPT_PARAMETER,
            "seed": _SEED_PARAMETER,
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["path", "prompt"],
    },
}

VIDEO_GENERATE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Generates a new video from a text description.",
    "use_when": (
        "the user wants a video created from scratch (e.g. "
        '"create a video of...", "generate a clip showing...").'
    ),
    "avoid_when": (
        "the user wants to animate an existing image instead (use "
        "`video_generate_from_image`), or wants an existing video "
        "transformed (use `video_edit`)."
    ),
    "requires": "a text description of the desired video.",
    "result_semantics": "Returns the generated video's output_path.",
    "failure_semantics": (
        "If no video-generation Provider model is currently "
        "available, explain the problem in plain language without "
        "exposing internal exception details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": _PROMPT_PARAMETER,
            "negative_prompt": _NEGATIVE_PROMPT_PARAMETER,
            "width": _WIDTH_PARAMETER,
            "height": _HEIGHT_PARAMETER,
            "duration_seconds": _DURATION_PARAMETER,
            "seed": _SEED_PARAMETER,
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["prompt"],
    },
}

VIDEO_GENERATE_FROM_IMAGE_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Animates an existing local image into a new video.",
    "use_when": (
        'the user wants an existing image turned into a video (e.g. '
        '"animate this image", "turn this photo into a video", '
        '"make this image move").'
    ),
    "avoid_when": (
        "the user wants a video generated from a text description "
        "alone (use `video_generate`), or wants an existing video "
        "transformed (use `video_edit`)."
    ),
    "requires": (
        "the source image file path; optionally a text instruction "
        "describing the desired motion/action."
    ),
    "result_semantics": "Returns the generated video's output_path.",
    "failure_semantics": (
        "If the image cannot be read or no compatible video-"
        "generation Provider model is currently available, explain "
        "the problem in plain language without exposing internal "
        "exception details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _IMAGE_PATH_PARAMETER,
            "instruction": {
                "type": "string",
                "description": (
                    "Optional description of the desired motion/"
                    "action. Defaults to a gentle, natural animation "
                    "of the image's contents."
                ),
            },
            "negative_prompt": _NEGATIVE_PROMPT_PARAMETER,
            "width": _WIDTH_PARAMETER,
            "height": _HEIGHT_PARAMETER,
            "duration_seconds": _DURATION_PARAMETER,
            "seed": _SEED_PARAMETER,
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["path"],
    },
}

VIDEO_EDIT_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Transforms an existing local video according to a text "
        "instruction (e.g. restyling its visual content)."
    ),
    "use_when": (
        'the user wants an existing video transformed (e.g. "turn '
        'this video into a cartoon style", "restyle this clip").'
    ),
    "avoid_when": (
        "the user wants a brand new video instead (use "
        "`video_generate`), or wants an image animated instead (use "
        "`video_generate_from_image`)."
    ),
    "requires": (
        "the source video file path and a text instruction describing "
        "the desired transformation."
    ),
    "result_semantics": "Returns the transformed video's output_path.",
    "failure_semantics": (
        "If the video cannot be read or no compatible video-editing "
        "Provider model is currently available, explain the problem "
        "in plain language without exposing internal exception "
        "details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": _VIDEO_PATH_PARAMETER,
            "prompt": {
                "type": "string",
                "description": "The desired transformation, as a text instruction.",
            },
            "negative_prompt": _NEGATIVE_PROMPT_PARAMETER,
            "width": _WIDTH_PARAMETER,
            "height": _HEIGHT_PARAMETER,
            "duration_seconds": _DURATION_PARAMETER,
            "seed": _SEED_PARAMETER,
            "output_path": _OUTPUT_PATH_PARAMETER,
        },
        "required": ["path", "prompt"],
    },
}
