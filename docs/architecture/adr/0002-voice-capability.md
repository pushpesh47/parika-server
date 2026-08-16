# ADR 0002: Server-Side Voice Capability (Speech-to-Text / Text-to-Speech)

> **Addendum (English/Hindi bilingual support).** Decisions 1-6 and
> their Alternatives/Consequences below describe the original Voice
> capability. Decisions 7-10 are an additive enhancement (no
> redesign): English/Hindi language model, automatic/explicit input
> language, Indian female Piper voices, a shared language-preference
> store, and the `GET`/`PUT /voice/settings` endpoint. See each
> decision's own text for exactly what changed and why.

## Context

PARIKA needed a server-side Voice capability so that any client (Web
UI, Console, mobile, desktop) can send audio, receive a transcript,
receive PARIKA's canonical text response, and optionally request
speech output -- without any client implementing its own speech
recognition/synthesis. The frozen architecture requires:

- Voice must not create a second reasoning pipeline: audio input must
  enter the exact same text pipeline (`Router` -> `Planner` -> `Brain`
  -> Provider/Tool -> response) a typed request already uses.
- Voice must not be an LLM provider; STT/TTS are speech capabilities,
  not reasoning providers.
- The canonical response is always text; text-to-speech is an
  independent, separately-controllable operation, never a fixed
  property of a PARIKA request.
- STT/TTS implementations must be provider/engine isolated and fully
  configuration-driven (model, device, language, voice, ...).

Before this change, the Core already anticipated Voice without ever
using it: `CapabilityCategory.SPEECH`, `ModelCapability.SPEECH_TO_TEXT`
/`TEXT_TO_SPEECH`, and `TaskCategory.SPEECH_TO_TEXT`/`TEXT_TO_SPEECH`
(with built-in requirement profiles) existed in the Model Selection
Framework, but no Module, Provider, or API endpoint used them.

## Decision

1. **Voice is a normal Module + Provider pair, mirroring the
   Generation Module exactly.** `parika/modules/voice/` registers two
   TOOL-category Capabilities (`voice.speech_to_text`,
   `voice.text_to_speech`, each with its own `tool.voice_*` Tool and
   Tool Affordance Contract) plus two internal, Provider-backed
   Capabilities (`voice.provider_speech_to_text`,
   `voice.provider_text_to_speech`). `parika/providers/local_speech/`
   is a normal `ProviderDriver` satisfying those two Provider
   Capabilities via `faster-whisper` (STT) and Piper (TTS), selected
   purely by `[providers.local_speech]` configuration. Neither STT nor
   TTS is a reasoning/chat provider; no LLM was introduced.

2. **A new, additive `CapabilityCategory.TEXT_TO_SPEECH` was added,
   distinct from the existing `SPEECH`.** Investigating the existing
   scaffolding surfaced a genuine gap: `Planner`'s
   `CATEGORY_TO_MODEL_CAPABILITY` mapped `CapabilityCategory.SPEECH`
   to the single hard-required `ModelCapability.SPEECH_TO_TEXT`
   regardless of whether a goal represented recognition or synthesis,
   which would have incorrectly forced any text-to-speech-only
   Provider model to also advertise `SPEECH_TO_TEXT` just to be
   selectable. This is fixed the same way `IMAGE_GENERATION`/
   `VIDEO_GENERATION` are already distinct from `VISION`: one new
   `CapabilityCategory` value, one new `CATEGORY_TO_MODEL_CAPABILITY`
   entry (`TEXT_TO_SPEECH -> ModelCapability.TEXT_TO_SPEECH`), and one
   new `_CATEGORY_TASK_DEFAULTS` entry -- three additive lines across
   two existing, frozen Core files, no renamed/removed behavior.
   Regression coverage: `tests/core/planner/test_planner.py::
   TestTextToSpeechCategoryIsIndependentFromSpeech`.

3. **STT/TTS engines are isolated behind small Protocols
   (`SttEngine`/`TtsEngine`), never imported by name outside
   `parika/providers/local_speech/engines/`.** `LocalSpeechProviderDriver`
   depends only on these Protocols; `faster_whisper`/`piper` packages
   are imported lazily, only when a concrete engine is actually
   constructed, so importing/registering this Provider never requires
   either optional dependency to be installed. This is what makes the
   implementation "provider/engine isolated" per the task requirement:
   a future engine only needs a new adapter module and one new branch
   in configuration-driven engine selection -- never a change to the
   Voice Module, the Voice API, or PARIKA Core.

4. **The Voice API never duplicates PARIKA's reasoning logic.**
   `POST /api/v1/voice/respond` transcribes audio
   (`voice.speech_to_text`) and then calls the *exact same*
   `parika.api.handlers.chat.handle_chat()` function
   `POST /api/v1/chat` already uses -- proven by
   `tests/api/routers/test_voice_router.py::
   test_respond_transcribes_and_submits_through_the_same_chat_pipeline`.
   `POST /api/v1/voice/transcribe` and `POST /api/v1/voice/speak` are
   independent, single-direction operations, following the existing
   `parika/api/` conventions (internal dispatch dataclasses in
   `requests.py`, `Route` bindings, translation-only handlers,
   `ApiModel` schemas).

5. **`voice.respond` never auto-triggers text-to-speech.** This is the
   single decision that makes every input/output combination (Section
   9) and every dynamic-preference-change scenario (Section 10)
   correct *by construction*, without inventing any special-case
   logic: the canonical text response is produced first, always, and
   a client decides -- independently, and only once the reply has
   actually arrived -- whether to separately call `POST /voice/speak`.
   A combined "respond and also speak" convenience endpoint was
   considered and rejected (see Alternatives).

6. **Speaking a long response is chunked, and cancellation is a
   distinct concept from `ProgressReporter`/`ToolManager`'s execution
   lifecycle.** `TextToSpeechToolDriver` splits input text into small,
   bounded chunks (`text_chunking.split_into_speech_chunks()`, default
   280 characters, `[voice].tts_chunk_max_characters`) and synthesizes
   one chunk at a time via a nested `Goal` per chunk (through the
   unmodified Planner/Model Selection Framework, exactly like every
   other Provider-backed Capability), checking a small,
   `ServiceContainer`-registered `TtsOperationRegistry` between chunks.
   `POST /voice/speak/{operation_id}/stop` cancels cooperatively:
   already-synthesized audio is still returned (`cancelled: true`),
   the Tool execution still reports exactly one `completed()` event
   (never `failed()` -- stopping is a normal, partial success), and
   nothing about the Tool execution's own lifecycle changes. This is
   deliberately a *different* concern from the shared `ToolManager`
   progress guard (see `parika/modules/voice/operation_registry.py`'s
   own docstring): the guard still, unmodified, guarantees exactly one
   terminal event per started progress node; cancellation instead
   answers "does the caller still want this audio", entirely
   independent of Tool execution success/failure.

7. **An explicit, additive English/Hindi language model
   (`parika/modules/voice/language.py`), never a broad
   internationalization framework.** `VoiceInputLanguage` (`AUTO`/
   `ENGLISH`/`HINDI`) and `VoiceOutputLanguage` (`ENGLISH`/`HINDI`/
   `FOLLOW_INPUT`) are the only new enums; the concrete, stable
   spoken-language codes remain the plain strings `"en"`/`"hi"`
   already used everywhere in `SpeechRequest.language`/
   `SpeechResult.language_detected` before this change -- no change to
   either type's shape, only one additive `SpeechResult.
   language_confidence: float | None` field. Input language (what
   should STT expect/detect) and output language (what should TTS
   speak) are kept deliberately distinct types, matching the task's
   own input/output separation requirement. `"auto"`/`"follow_input"`
   are *policies* resolved to a concrete `"en"`/`"hi"` value entirely
   inside the Voice Module boundary (`driver_stt.py`/`driver_tts.py`),
   before a nested Provider `Goal` is ever built -- Core (Brain/
   Planner/Router/ProviderManager) never sees either policy value,
   preserving Section 29's "PARIKA Core remains language-agnostic"
   boundary exactly.

8. **Automatic language detection comes from faster-whisper itself,
   never a Unicode-script/keyword heuristic and never the chat
   model.** `FasterWhisperSttEngine.transcribe()` already accepted an
   optional `language` hint (`None` = auto-detect) before this change;
   the only addition is capturing `info.language_probability` (when
   the underlying engine reports one -- only in true auto-detect mode,
   since forcing a language skips the recognizer's own detection pass)
   as the new, honestly-nullable `SttEngineResult.language_probability`/
   `SpeechResult.language_confidence` field -- never fabricated. A
   `.en`-suffixed (English-only) `stt_model_size` explicitly rejects a
   Hindi request with a clear, actionable error rather than silently
   mis-transcribing or crashing. An unsupported detected language
   (neither `en` nor `hi`) is reported as `language_source:
   "unsupported"` with the raw detected code still surfaced -- the
   transcript itself is never discarded or silently relabeled as
   English/Hindi.

9. **Indian female TTS voices, added as a second, independent Piper
   voice "slot" per language -- never a single generic voice, and
   never a fabricated "Indian English" voice.** Investigating Piper's
   actual upstream voice catalog (`rhasspy/piper-voices`,
   `github.com/rhasspy/piper/blob/master/VOICES.md`) before choosing
   any identifier (per the task's own "do not invent voice
   identifiers" requirement) found:
   - **Hindi (`hi_IN`):** `hi_IN-priyamvada-medium` is a real,
     confirmed-female Hindi/India voice -- genuinely Indian, Hindi,
     and female. Configured as `[providers.local_speech]
     .tts_hindi_voice`/`tts_hindi_model_path`/`tts_hindi_config_path`/
     `tts_hindi_speaker_id`, alongside the pre-existing English slot
     (`tts_voice`/`tts_model_path`/`tts_config_path`/`tts_speaker_id`,
     unchanged field names, so no existing configuration/test breaks).
   - **English:** Piper's official catalog has **no** dedicated
     Indian-English (`en_IN`) locale at all -- only `en_US`/`en_GB`.
     There is therefore no real Indian-English Piper voice to
     configure; per the task's own instruction ("if unavailable, do
     not pretend a voice is Indian female... document the exact
     limitation and use the closest supported voice only if the
     project explicitly allows fallback"), the default `tts_voice`
     changed from the previous male `en_US-lessac-medium` to the
     closest real, confirmed-**female** substitute,
     `en_US-amy-medium` -- a genuine improvement (female, as
     required) with an explicitly documented, honest gap (not
     Indian-accented). This limitation is recorded here, in
     `config/defaults.toml`'s own comment block, and in the Final
     Report; it is not hidden.
   - `PiperTtsEngine` was extended (backward compatible: the existing
     `model_path`/`config_path`/`device`/`speaker_id`/`length_scale`/
     `noise_scale`/`noise_w` constructor contract is unchanged) with an
     optional `additional_voices: Mapping[str, PiperVoiceSpec]`
     parameter and a `language` parameter on `synthesize()`: the
     primary (English) voice still loads eagerly at construction
     exactly as before; each additional voice (Hindi) loads lazily,
     only the first time it is actually requested, preserving "keep
     model loading lazy" (Section 6) and never loading two Whisper/
     Piper models unless a request genuinely needs both. Requesting an
     unconfigured language falls back to the primary voice rather than
     raising -- consistent with "gracefully degrade", never fabricating
     a voice/language that was not actually configured.

10. **One new, additive, `TtsOperationRegistry`-shaped shared
    preference store (`VoiceLanguagePreferenceStore`), never a second
    output-preference mechanism, a `LanguageManager`, or a
    `VoiceSessionManager`.** Investigating the existing "dynamic
    output preference" architecture (Section 9/19 of the task) found
    that no server-side output-preference registry exists at all
    today: whether to speak a reply is, and remains, a fully
    client-side decision enforced by `voice.respond` never calling the
    text-to-speech Tool (Decision 5, unchanged). *Which language* to
    use is a genuinely new, narrower piece of state this task
    explicitly asks for (Sections 8/9/13), so `VoiceLanguagePreferenceStore`
    extends that same principle rather than duplicating it: it is a
    single, small, `RLock`-guarded, `ServiceContainer`-registered
    singleton -- structurally identical to the pre-existing
    `TtsOperationRegistry` (same sharing pattern between the Voice
    Module's two `ToolDriver`s and the Voice API) -- holding exactly
    three facts: the current input-language preference, the current
    output-language preference, and the most recently detected/used
    input language (consulted only by `FOLLOW_INPUT`). Seeded at
    startup from `[voice].input_language`/`output_language`;
    afterwards, `GET`/`PUT /api/v1/voice/settings` (the smallest
    appropriate new API surface -- no pre-existing settings mechanism
    covers Voice language preference) reads/updates the *current*
    preference without touching configuration. TTS language
    resolution order (`resolve_output_language()`): explicit per-
    request `language` -> current output-language preference (`en`/
    `hi` directly) -> `FOLLOW_INPUT` against the last detected/used
    input language -> a configured fallback (`"en"`). Changing this
    preference mid-request never cancels, modifies, or otherwise
    affects an already in-flight `ChatRequest`/`VoiceRespondRequest` --
    only the *next* `speak`/`transcribe` call observes it, exactly
    mirroring how a `speak`-vs-not-speak decision already worked
    before this change.

## Alternatives Considered

- **A combined `respond(..., speak=true)` convenience call.**
  Rejected: in a synchronous request/response model, embedding
  `speak` into the same call as `respond` reproduces exactly the bad
  scenario Section 10 describes (the user changes their mind about
  voice output while PARIKA is still processing, but the server has
  already committed to speaking by the time the response returns).
  Two independent calls (`respond`, then optionally `speak`) is not a
  limitation of this implementation -- it is the only way every
  dynamic-preference-change scenario stays correct.
- **Routing TTS cancellation through `ToolManager`/`ProgressReporter`
  itself** (e.g. a `cancel()` method on the guard). Rejected: the
  guard's job is narrowly "did every started node receive exactly one
  terminal event", which remains entirely correct and untouched;
  conflating it with "does the caller still want this output" would
  have required changing frozen, already-tested Core lifecycle
  machinery for a concern that is not actually about execution
  lifecycle at all.
- **A single `ProviderModel` per engine package (one for faster-whisper,
  one for Piper) sharing one `CapabilityCategory`.** Superseded by
  Decision 2: once `TEXT_TO_SPEECH` existed as its own category, STT
  and TTS becoming two independent `ProviderModel`s (see
  `parika.providers.local_speech.discovery`) was the natural, correct
  shape -- each direction can be installed/configured independently
  (e.g. `faster-whisper` present but no Piper voice model configured
  yet still offers `voice.speech_to_text`).
- **Streaming TTS output today.** Rejected for this increment: no
  audio-streaming transport exists yet (the API layer's only
  streaming transport is the chat WebSocket's token stream). The
  chunked-synthesis design is deliberately compatible with a future
  streaming endpoint (each chunk is already an independent, ordered
  unit) without inventing an unrelated streaming system now.
- **`piper-tts` excluded entirely over its GPL-3.0-or-later license.**
  Rejected: it remains strictly optional (the `voice` extra, never a
  base dependency), exactly like every other optional extra in
  `pyproject.toml`; installing it is the operator's own explicit
  choice. Flagged here, and in `pyproject.toml`'s own comment, so the
  choice is visible rather than silent.
- **A Unicode-script/keyword heuristic for language detection (e.g.
  "if text contains Devanagari characters, it's Hindi").** Explicitly
  rejected by the task itself: language must come from the speech
  recognition layer (faster-whisper's own detection), never a
  post-hoc text heuristic or an LLM guess -- a heuristic would also be
  wrong for the exact case the task calls out (Hinglish/mixed-language
  utterances, romanized Hindi, and short utterances with too little
  text to classify reliably).
- **A custom Hinglish language category.** Rejected: the supported
  language model stays exactly `en`/`hi`/`auto`, as specified. Mixed-
  language speech is handled exactly as faster-whisper itself handles
  it -- it returns one single language classification for the whole
  utterance; PARIKA passes that through as-is (`language_source`
  reflects whether it was `en`/`hi`-supported or not) rather than
  attempting to split, reclassify, or improve on it.
- **A hidden translation subsystem (e.g. auto-translating the
  canonical text response before speaking it in a different requested
  output language).** Explicitly rejected by the task: if the
  canonical response's language and the resolved output language
  differ, PARIKA speaks the canonical text as-is in the resolved
  voice/language rather than silently feeding mismatched text through
  an invented LLM-translation step. This is a documented limitation,
  not a hidden behavior change.
- **A single, generic `tts_model_path`/`tts_voice` pair extended with a
  `language=` argument that swaps the *same* loaded model's locale at
  request time.** Rejected: Piper voice models are single-language,
  single-checkpoint artifacts (no runtime locale switch exists in the
  library); two independent, lazily-loaded voice "slots"
  (`PiperVoiceSpec`/`additional_voices`) is what the underlying engine
  actually supports, and is also what makes each language
  independently configurable/available (Section 18's requirement).
- **A per-session `VoiceSessionManager` keyed by `session_id`, rather
  than one shared `VoiceLanguagePreferenceStore`.** Rejected: PARIKA
  has no multi-tenant/per-account preference concept today (it is a
  personal assistant, single operator), and the Voice API's existing
  `speak`/`stop_speaking` operations are already not session-scoped
  (`VoiceSpeakRequest` carries no `session_id`). Introducing session-
  scoping only for language preference would be exactly the "second,
  parallel state mechanism" Section 29 forbids; a single shared
  "current preference", read/settable independently of any specific
  request, is the direct extension of the pre-existing "current
  output preference" principle (Decision 5) the task explicitly asks
  for.

## Consequences

- Two new, additive Core types: `SpeechRequest`/`SpeechOperation` and
  `SpeechResult` (`parika/core/provider_manager/`), mirroring
  `GenerationRequest`/`GenerationResult` exactly. No existing
  Core type changed.
- One new, additive `CapabilityCategory` value (`TEXT_TO_SPEECH`) and
  two new, additive dictionary entries in `planner.py`/
  `task_classification.py` (Decision 2). No existing category's
  routing behavior changed.
- Two new optional dependencies (`faster-whisper`, `piper-tts`, the
  `voice` extra) -- never required for PARIKA to install, start, or
  run; `voice.speech_to_text`/`voice.text_to_speech` simply have no
  compatible Provider model (never a crash) until installed and
  configured.
- New configuration sections `[providers.local_speech]` and `[voice]`
  in `config/defaults.toml`, following the project's existing
  enable-flag/model-selection/device-selection conventions (mirroring
  `[providers.comfyui]`).
- Four new REST endpoints under `/api/v1/voice/`, following the
  existing `parika/api/` conventions exactly (internal dispatch
  dataclasses, `Route` bindings, `ApiModel` schemas, the centralized
  suffix-based error-mapping table -- no new error-handling mechanism).
- Existing Image Generation, Video Generation, and every other
  Module/Provider/endpoint are unchanged; the full existing test suite
  (2797 tests) passes unmodified alongside the new Voice test suite.

### Consequences of the English/Hindi bilingual enhancement (Decisions 7-10)

- One new module, `parika/modules/voice/language.py`
  (`VoiceInputLanguage`, `VoiceOutputLanguage`, `VoiceLanguagePreference`,
  `VoiceLanguagePreferenceStore`, parse/validate helpers). No existing
  Voice Module file was rewritten -- `driver_stt.py`/`driver_tts.py`/
  `module_driver.py`/`config.py`/`tool_affordances.py` were extended,
  not redesigned.
- Additive fields only on existing Core/provider types:
  `SpeechResult.language_confidence`,
  `SttEngineResult.language_probability`. No existing field removed
  or renamed.
- `TtsEngine.synthesize()`/`PiperTtsEngine.synthesize()` gained an
  optional `language` parameter; `PiperTtsEngine.__init__()` gained
  optional `language`/`additional_voices` parameters -- every existing
  positional/keyword argument, and every existing caller that never
  mentions either new parameter, is unaffected.
- `[providers.local_speech]` gained four new, additive keys
  (`tts_hindi_voice`, `tts_hindi_model_path`, `tts_hindi_config_path`,
  `tts_hindi_speaker_id`); `[voice]` gained two (`input_language`,
  `output_language`). No existing key removed; `tts_voice`'s *default
  value* changed from `en_US-lessac-medium` (male) to `en_US-amy-medium`
  (female) -- an explicit, documented value change, not a schema
  change.
- Two new REST endpoints, `GET`/`PUT /api/v1/voice/settings`, using
  the exact same conventions as every other endpoint in
  `parika/api/` (internal dispatch dataclasses, `Route` bindings,
  `ApiModel` schemas with `field_validator`-based language validation
  producing normal `422` responses, centralized error mapping). The
  four pre-existing endpoints gained additive response fields only
  (`requested_input_language`, `detected_input_language`,
  `language_source`, `output_language`); no existing response field
  was removed or repurposed.
- `/status` gained one additive `Voice:` section (input/output
  language, configured English/Hindi voice labels, STT/TTS
  availability); no existing `/status` line changed. `/help`/`/config`
  are unchanged (no new command was added; `/config` already surfaces
  the new configuration keys generically).
- `spinner_view.py`'s `_KEYWORD_LABELS` gained three additive entries
  (`speech_to_text`, `text_to_speech`, `voice`); no existing entry
  changed.
- No new `LanguageManager`, `TranslationManager`, or
  `VoiceSessionManager` was introduced; no Hinglish category was
  introduced; no translation subsystem was introduced; Brain/Planner/
  Router/ProviderManager received zero language-specific logic.
- The full test suite (2944 tests, including this enhancement's new
  and updated Voice/local-speech/API tests) passes unmodified.
