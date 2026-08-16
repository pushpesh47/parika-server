"""
PARIKA Vision Module - Tool Affordance Contracts (Phase 4)

Tool Affordance Contracts for `vision.search_images`,
`vision.find_similar_images`, and `vision.find_duplicates` -- split
out of `module_driver.py` purely to keep that file within the
project's File Size Guidelines.
"""

from __future__ import annotations

from typing import Any, Mapping

_CANDIDATE_SET_PROPERTIES: Mapping[str, Any] = {
    "paths": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Explicit list of candidate image file paths.",
    },
    "directory": {
        "type": "string",
        "description": "A directory to search for candidate images in, instead of an explicit 'paths' list.",
    },
    "pattern": {
        "type": "string",
        "description": "Optional glob filter applied when 'directory' is given (e.g. '*.png').",
    },
}

VISION_SEARCH_IMAGES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Searches a set of local images for ones matching a natural-"
        "language description, using a Vision model per candidate "
        "(bounded by max_candidates) -- genuinely semantic, since no "
        "deterministic algorithm can recognize image content."
    ),
    "use_when": "the user wants to find which image(s) in a set show something described in words.",
    "avoid_when": (
        "the user already knows which images to compare and just "
        "wants a similarity ranking (use `vision_find_similar_images`, "
        "which never calls a model by default)."
    ),
    "requires": "the natural-language query, and either an explicit 'paths' list or a 'directory'.",
    "result_semantics": "Returns the matching image paths with a brief justification each. Present them directly.",
    "failure_semantics": (
        "If the directory/paths cannot be resolved or no Vision-"
        "capable model is available, explain the problem in plain "
        "language. Mention when candidates were truncated by "
        "max_candidates."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for, in natural language."},
            **_CANDIDATE_SET_PROPERTIES,
            "max_candidates": {
                "type": "integer",
                "description": "Optional cap on how many candidate images to check with the Vision model.",
            },
        },
        "required": ["query"],
    },
}

VISION_FIND_SIMILAR_IMAGES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Ranks a set of local images by deterministic (perceptual-"
        "hash/pixel/histogram) similarity to a reference image, never "
        "calling a model unless verify_with_model is explicitly set."
    ),
    "use_when": "the user wants the most visually similar images to a given one, from a set.",
    "avoid_when": "the user wants images matching a text description instead (use `vision_search_images`).",
    "requires": "the reference image path, and either an explicit 'paths' list or a 'directory'.",
    "result_semantics": "Returns the top matches ranked by overall_similarity. Present them directly.",
    "failure_semantics": "If the reference image or directory/paths cannot be resolved, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            "reference_path": {"type": "string", "description": "The image to compare every candidate against."},
            **_CANDIDATE_SET_PROPERTIES,
            "top_k": {"type": "integer", "description": "Optional maximum number of matches to return (default 10)."},
            "verify_with_model": {
                "type": "boolean",
                "description": "Optional. When true, additionally asks a Vision model to explain the single best match.",
            },
        },
        "required": ["reference_path"],
    },
}

VISION_FIND_DUPLICATES_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": (
        "Groups a set of local images into deterministic near-"
        "duplicate clusters (perceptual-hash Hamming distance), never "
        "calling a model unless verify_with_model is explicitly set."
    ),
    "use_when": "the user wants duplicate or near-duplicate images found within a set.",
    "avoid_when": "the user only has two specific images to compare (use `vision_compare_images`).",
    "requires": "either an explicit 'paths' list or a 'directory'.",
    "result_semantics": "Returns each duplicate group's paths. Present them directly.",
    "failure_semantics": "If the directory/paths cannot be resolved, explain the problem in plain language.",
    "parameters": {
        "type": "object",
        "properties": {
            **_CANDIDATE_SET_PROPERTIES,
            "verify_with_model": {
                "type": "boolean",
                "description": "Optional. When true, additionally asks a Vision model to confirm the top duplicate group.",
            },
        },
        "required": [],
    },
}
