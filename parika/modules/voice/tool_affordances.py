"""
PARIKA Voice Module - Tool Affordance Contracts

The Tool Affordance Contract (`metadata["tool_affordance"]`) for each
of this Module's two advertised `voice.*` Capabilities, consumed
generically by AI Context Engineering
(`parika/interfaces/ai_context/tool_context.py`) -- exactly the same
contract shape every other Module's affordances already use.

Neither parameter schema mentions faster-whisper, Kokoro, a model
path, a device, or any other provider-specific concept: they describe
only the semantic speech operation, matching the architecture's
requirement that clients/callers never need to know which engine
PARIKA uses.
"""

from __future__ import annotations

from typing import Any, Mapping

_INPUT_LANGUAGE_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "enum": ["auto", "en", "hi"],
    "description": (
        "Requested input language: \"auto\" (the default; let the "
        "engine detect English or Hindi itself), \"en\", or \"hi\". "
        "Omit to use the current Voice input-language preference."
    ),
}

_OUTPUT_LANGUAGE_PARAMETER: Mapping[str, Any] = {
    "type": "string",
    "enum": ["en", "hi"],
    "description": (
        "Requested output language: \"en\" or \"hi\". Omit to use the "
        "current Voice output-language preference (which may itself "
        "follow whichever language was most recently spoken)."
    ),
}

# Backward-compatible alias: earlier revisions of this Module exposed
# one shared `_LANGUAGE_PARAMETER` for both directions. Input and
# output language are now kept explicitly distinct (see this
# Module's own `language.py`), but the name is kept importable in case
# any external code still references it.
_LANGUAGE_PARAMETER = _INPUT_LANGUAGE_PARAMETER

SPEECH_TO_TEXT_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Transcribes audio into text.",
    "use_when": (
        "the user provides an audio recording/file and wants its "
        "spoken content transcribed."
    ),
    "avoid_when": (
        "the user wants a spoken response synthesized instead (use "
        "`voice_text_to_speech`)."
    ),
    "requires": (
        "an existing local audio file path; ask the user for one if "
        "not already known."
    ),
    "result_semantics": (
        "Returns the transcribed text plus the detected/used language "
        "(English or Hindi -- automatically detected by the speech "
        "engine itself when \"auto\", never guessed from the text)."
    ),
    "failure_semantics": (
        "If the audio cannot be read or no speech-to-text Provider "
        "model is currently available, explain the problem in plain "
        "language without exposing internal exception details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Absolute or root-relative filesystem path of "
                    "the source audio file."
                ),
            },
            "language": _INPUT_LANGUAGE_PARAMETER,
        },
        "required": ["path"],
    },
}

TEXT_TO_SPEECH_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "purpose": "Synthesizes text into spoken audio.",
    "use_when": (
        'the user asks for a response to be read aloud/spoken (e.g. '
        '"read this back to me", "say this out loud").'
    ),
    "avoid_when": (
        "the user provided audio and wants it transcribed instead "
        "(use `voice_speech_to_text`)."
    ),
    "requires": "the text to synthesize.",
    "result_semantics": (
        "Returns the synthesized audio (base64-encoded WAV) and, if "
        "`output_path` was supplied, the path it was also written to."
    ),
    "failure_semantics": (
        "If no text-to-speech Provider model is currently available, "
        "explain the problem in plain language without exposing "
        "internal exception details."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to synthesize.",
            },
            "voice": {
                "type": "string",
                "description": (
                    "Optional voice/speaker identifier hint. Omit to "
                    "use the configured default voice."
                ),
            },
            "language": _OUTPUT_LANGUAGE_PARAMETER,
            "output_path": {
                "type": "string",
                "description": (
                    "Optional path to also persist the synthesized "
                    "audio to, in addition to returning it inline."
                ),
            },
        },
        "required": ["text"],
    },
}
