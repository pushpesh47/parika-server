"""
PARIKA Local Speech Provider - Engine Adapters

Isolates the Local Speech provider driver from any specific STT/TTS
implementation behind two small Protocols (`SttEngine`/`TtsEngine`),
exactly the "provider/engine isolated" requirement the Voice
capability's architecture mandates: `LocalSpeechProviderDriver` never
imports `faster_whisper`/`kokoro_onnx` (or any other concrete engine
package) directly -- only through these Protocols. Swapping the
underlying engine later requires a new module implementing the
relevant Protocol -- never a change to the Voice Module, the Voice
API, or PARIKA Core.
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
