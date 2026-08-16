"""
PARIKA Voice Module - Capability/Tool Id Constants

Every `voice.*` capability and tool id this Module registers, in one
place, following the project's frozen naming convention (capabilities:
`<domain>.<verb>_<object>`; tools: `tool.<domain>_<verb>_<object>`).

Mirrors `parika.modules.generation.capability_ids`'s two-Capability-
per-Tool shape exactly: an advertised `TOOL`-category capability plus
an internal, Provider-backed capability for each of the two Voice
operations (speech-to-text, text-to-speech).
"""

from __future__ import annotations

SPEECH_TO_TEXT_CAPABILITY_ID = "voice.speech_to_text"
SPEECH_TO_TEXT_PROVIDER_CAPABILITY_ID = "voice.provider_speech_to_text"
SPEECH_TO_TEXT_TOOL_ID = "tool.voice_speech_to_text"

TEXT_TO_SPEECH_CAPABILITY_ID = "voice.text_to_speech"
TEXT_TO_SPEECH_PROVIDER_CAPABILITY_ID = "voice.provider_text_to_speech"
TEXT_TO_SPEECH_TOOL_ID = "tool.voice_text_to_speech"
