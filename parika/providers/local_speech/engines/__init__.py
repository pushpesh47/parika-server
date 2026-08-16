"""
PARIKA Local Speech Provider - Engine Adapters

Isolates the Local Speech provider driver from any specific STT/TTS
implementation behind two small Protocols (`SttEngine`/`TtsEngine`),
exactly the "provider/engine isolated" requirement the Voice
capability's architecture mandates: `LocalSpeechProviderDriver` never
imports `faster_whisper`/`piper` (or any other concrete engine
package) directly -- only through these Protocols, selected at
construction time by `[providers.local_speech].stt_engine`/
`tts_engine`. Swapping the underlying engine later requires a new
module implementing the relevant Protocol and one new branch in
`driver.py`'s engine-selection helper -- never a change to the Voice
Module, the Voice API, or PARIKA Core.
"""

from __future__ import annotations

from .stt_engine import SttEngine, SttEngineResult
from .tts_engine import TtsEngine, TtsEngineResult

__all__ = [
    "SttEngine",
    "SttEngineResult",
    "TtsEngine",
    "TtsEngineResult",
]
