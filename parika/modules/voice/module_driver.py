"""
PARIKA Voice Module - Driver

Implements the `ModuleDriver` contract for the Voice Module, following
exactly the same two-Capability-per-Tool shape
`GenerationModuleDriver`/`VisionModuleDriver` already establish:

On start(), for each of the two `voice.*` Tool specs declared in
`_VOICE_TOOL_SPECS` below, registers:

- Its advertised TOOL Capability (`voice.speech_to_text`/
  `voice.text_to_speech`, `CapabilityCategory.TOOL`) with its own
  `tool.voice_*` Tool -- advertised to the general chat model through
  Automatic Capability Discovery/its own Tool Affordance Contract.
- Its internal, Provider-backed Capability (`voice.provider_
  speech_to_text`/`voice.provider_text_to_speech`,
  `CapabilityCategory.SPEECH`/`TEXT_TO_SPEECH`) -- satisfied by a
  compatible speech Provider model (the Local Speech Provider today),
  never a Tool, and never advertised directly to the general chat
  model.

The `text_to_speech` Tool additionally shares one `TtsOperationRegistry`
(constructed by the composition root, see `parika/interfaces/runtime.py`,
and also registered in `ServiceContainer` so the Voice API's
`/voice/speak/{operation_id}/stop` handler observes the exact same
registry) with its `TextToSpeechToolDriver` -- see
`operation_registry.py`'s own docstring for why this is a distinct
concern from `ProgressReporter`/`ToolManager`'s execution-lifecycle
guard.

Both ToolDrivers additionally share one `VoiceLanguagePreferenceStore`
(same composition-root/`ServiceContainer` sharing pattern, seeded from
`[voice].input_language`/`output_language`) so the Voice API's
settings endpoints (`GET`/`PUT /voice/settings`) can read/update the
exact same "current Voice language preference" both `voice.
speech_to_text` and `voice.text_to_speech` consult -- see
`language.py`'s own docstring.

On stop(), unregisters all four.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from parika.core.brain.brain import Brain
from parika.core.capability_registry.capability_category import CapabilityCategory
from parika.core.capability_registry.capability_definition import (
    CapabilityDefinition,
)
from parika.core.capability_registry.capability_registry import CapabilityRegistry
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.health_manager.health_check_result import HealthCheckResult
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.driver import ModuleDriver
from parika.core.tool_manager.tool import Tool
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import ProgressReporter

from . import capability_ids as ids
from . import tool_affordances as affordances
from .config import load_voice_config
from .driver_stt import SpeechToTextToolDriver
from .driver_tts import TextToSpeechToolDriver
from .language import VoiceLanguagePreference, VoiceLanguagePreferenceStore
from .operation_registry import TtsOperationRegistry

VOICE_TOOL_VERSION = "1.0.0"
MODULE_HEALTH_COMPONENT_ID = "module.voice"


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceToolSpec:
    """
    Immutable declaration of one `voice.*` TOOL Capability/Tool pair
    and the internal, Provider-backed Capability it orchestrates.
    """

    tool_capability_id: str
    provider_capability_id: str
    tool_id: str
    name: str
    tool_description: str
    provider_description: str
    provider_category: CapabilityCategory
    tool_affordance: Mapping[str, Any]


_VOICE_TOOL_SPECS: tuple[VoiceToolSpec, ...] = (
    VoiceToolSpec(
        tool_capability_id=ids.SPEECH_TO_TEXT_CAPABILITY_ID,
        provider_capability_id=ids.SPEECH_TO_TEXT_PROVIDER_CAPABILITY_ID,
        tool_id=ids.SPEECH_TO_TEXT_TOOL_ID,
        name="Voice - Speech to Text",
        tool_description=(
            "Orchestrates a Provider-backed speech recognition model "
            "to transcribe audio into text."
        ),
        provider_description=(
            "Local, on-device speech-to-text, satisfied by a "
            "Provider model specialized for speech recognition "
            "(e.g. the Local Speech Provider's faster-whisper model)."
        ),
        provider_category=CapabilityCategory.SPEECH,
        tool_affordance=affordances.SPEECH_TO_TEXT_TOOL_AFFORDANCE,
    ),
    VoiceToolSpec(
        tool_capability_id=ids.TEXT_TO_SPEECH_CAPABILITY_ID,
        provider_capability_id=ids.TEXT_TO_SPEECH_PROVIDER_CAPABILITY_ID,
        tool_id=ids.TEXT_TO_SPEECH_TOOL_ID,
        name="Voice - Text to Speech",
        tool_description=(
            "Orchestrates a Provider-backed speech synthesis model "
            "to convert text into spoken audio."
        ),
        provider_description=(
            "Local, on-device text-to-speech, satisfied by a "
            "Provider model specialized for speech synthesis (e.g. "
            "the Local Speech Provider's Piper voice model)."
        ),
        provider_category=CapabilityCategory.TEXT_TO_SPEECH,
        tool_affordance=affordances.TEXT_TO_SPEECH_TOOL_AFFORDANCE,
    ),
)


class VoiceModuleDriver(ModuleDriver):
    """
    Runtime driver for the Voice Module.
    """

    def __init__(
        self,
        *,
        capability_registry: CapabilityRegistry,
        tool_manager: ToolManager,
        brain: Brain,
        logger: Logger,
        operation_registry: TtsOperationRegistry | None = None,
        language_preference: VoiceLanguagePreferenceStore | None = None,
        event_bus: EventBus | None = None,
        health_manager: HealthManager | None = None,
        configuration: Configuration | None = None,
    ) -> None:
        self._capability_registry = capability_registry
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)

        voice_config = load_voice_config(configuration)
        self._enabled = voice_config.enabled
        self.operation_registry = operation_registry or TtsOperationRegistry()
        self.language_preference = language_preference or VoiceLanguagePreferenceStore(
            default=VoiceLanguagePreference(
                input_language=voice_config.input_language,
                output_language=voice_config.output_language,
            )
        )

        def _progress_for(capability_id: str) -> ProgressReporter | None:
            return (
                ProgressReporter(event_bus, capability_id)
                if event_bus is not None
                else None
            )

        self._tool_drivers: dict[str, Any] = {
            ids.SPEECH_TO_TEXT_CAPABILITY_ID: SpeechToTextToolDriver(
                brain=brain,
                provider_capability_id=(
                    ids.SPEECH_TO_TEXT_PROVIDER_CAPABILITY_ID
                ),
                language_preference=self.language_preference,
                progress_reporter=_progress_for(
                    ids.SPEECH_TO_TEXT_CAPABILITY_ID
                ),
            ),
            ids.TEXT_TO_SPEECH_CAPABILITY_ID: TextToSpeechToolDriver(
                brain=brain,
                provider_capability_id=(
                    ids.TEXT_TO_SPEECH_PROVIDER_CAPABILITY_ID
                ),
                config=voice_config,
                operation_registry=self.operation_registry,
                language_preference=self.language_preference,
                progress_reporter=_progress_for(
                    ids.TEXT_TO_SPEECH_CAPABILITY_ID
                ),
            ),
        }

    def start(self) -> None:
        if not self._enabled:
            self._logger.info(
                "Voice module is disabled by configuration; not "
                "registering its Capabilities or Tools."
            )
            return

        for spec in _VOICE_TOOL_SPECS:
            self._capability_registry.register(
                CapabilityDefinition(
                    id=spec.tool_capability_id,
                    name=spec.name,
                    description=spec.tool_description,
                    # TOOL, not SPEECH/TEXT_TO_SPEECH: Planner routes
                    # a Goal to ToolManager only when `category is
                    # CapabilityCategory.TOOL` -- and Automatic
                    # Capability Discovery only ever advertises
                    # TOOL-category Capabilities to the model. This
                    # Capability is backed by a real, deterministic-
                    # dispatch ToolDriver, so it must be TOOL for
                    # either to work, exactly like `image.generate`.
                    category=CapabilityCategory.TOOL,
                    tags=frozenset({"voice", "speech", "media"}),
                    metadata={  # type: ignore[arg-type]
                        "tool_affordance": spec.tool_affordance
                    },
                )
            )
            self._tool_manager.register(
                Tool(
                    id=spec.tool_id,
                    name=spec.name,
                    version=VOICE_TOOL_VERSION,
                    description=spec.tool_description,
                    capabilities=(spec.tool_capability_id,),
                ),
                self._tool_drivers[spec.tool_capability_id],
            )

            self._capability_registry.register(
                CapabilityDefinition(
                    id=spec.provider_capability_id,
                    name=f"{spec.name} (Provider)",
                    description=spec.provider_description,
                    # SPEECH/TEXT_TO_SPEECH, Provider-routed -- never
                    # a Tool, and never advertised to the general
                    # chat model.
                    category=spec.provider_category,
                    tags=frozenset({"voice", "speech"}),
                )
            )

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("Voice module started.")

    def stop(self) -> None:
        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        for spec in _VOICE_TOOL_SPECS:
            self._tool_manager.unregister(spec.tool_id)
            self._capability_registry.unregister(spec.tool_capability_id)
            self._capability_registry.unregister(spec.provider_capability_id)

        self._logger.info("Voice module stopped.")

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)
