"""
PARIKA Voice Module - Manifest

Defines the static ModuleManifest describing the Voice Module.

Registers `voice.speech_to_text` and `voice.text_to_speech`:
Tool-backed orchestrators that delegate the actual speech recognition/
synthesis to their own internal, Provider-backed Capabilities --
satisfied today by the Local Speech Provider
(`parika.providers.local_speech`), but never hard-coded to it; any
future compatible speech Provider (declaring `ModelCapability
.SPEECH_TO_TEXT`/`TEXT_TO_SPEECH`) is automatically eligible through
the unmodified Model Selection Framework.

Voice remains a server-side capability around PARIKA's existing,
unmodified text pipeline (see `docs/architecture/Voice_Capability
_Design.md`): the Voice API (`parika/api/routers/voice.py`) converts
audio to text via `voice.speech_to_text` and then submits that text
through the exact same `InterfaceSession.submit_text()`/`chat.respond`
path a typed request already uses -- this Module never introduces a
second reasoning pipeline.
"""

from __future__ import annotations

from parika.core.module_manager.manifest import ModuleManifest
from parika.core.module_manager.module import Module
from parika.core.module_manager.state import ModuleState

from .module_driver import VoiceModuleDriver

VOICE_MODULE_ID = "voice"
VOICE_MODULE_VERSION = "1.0.0"


def create_voice_module_manifest() -> ModuleManifest:
    """
    Build the immutable ModuleManifest for the Voice Module.
    """

    return ModuleManifest(
        id=VOICE_MODULE_ID,
        name="Voice",
        version=VOICE_MODULE_VERSION,
        description=(
            "Registers the speech family: `voice.speech_to_text` and "
            "`voice.text_to_speech` (Tool-backed orchestrators that "
            "delegate to a Provider-backed speech recognition/"
            "synthesis model), together with their internal, "
            "SPEECH/TEXT_TO_SPEECH-category Provider Capabilities, "
            "each satisfied by a compatible Provider model (e.g. the "
            "Local Speech Provider's faster-whisper/Piper engines), "
            "never advertised directly to the general chat model."
        ),
        author="PARIKA",
        license="MIT",
        tags=("voice", "speech", "audio"),
        driver="parika.modules.voice.module_driver.VoiceModuleDriver",
    )


def create_voice_module(driver: VoiceModuleDriver) -> Module:
    """
    Build the immutable Module descriptor for the Voice Module.
    """

    return Module(
        id=VOICE_MODULE_ID,
        manifest=create_voice_module_manifest(),
        driver=driver,
        state=ModuleState.INACTIVE,
    )
