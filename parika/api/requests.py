"""
PARIKA API - Internal Dispatch Requests

Defines the small, immutable "internal operation" dataclasses used
*only* to dispatch through the existing `Router` Core component
(`parika/api/router_bindings.py`; see `docs/guides/Running.md`
section 12 for the Server Platform this supports).

These types are deliberately distinct from both:

- The Pydantic HTTP/WebSocket schemas in `parika/api/schemas/`, which
  validate wire-format JSON payloads and are never passed to `Router`.
- Any Core type (`Goal`, `BrainRequest`, `ToolRequest`, ...), which
  remain constructed only inside the existing Interface layer
  (`parika/interfaces/`) or Core itself.

Each dataclass here names one internal *operation* (not one HTTP
endpoint -- several endpoints may map to the same operation with
different parameters). `Router.select()` matches by `isinstance()`
against these exact types, so each one must remain a distinct class
even when structurally similar to another.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True, kw_only=True)
class StatusRequest:
    """Requests the aggregate runtime status snapshot."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolsListRequest:
    """Requests the list of registered Tools."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ModulesListRequest:
    """Requests the list of registered Modules."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleStartRequest:
    """Requests that a registered Module be started (loaded)."""

    module_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleStopRequest:
    """Requests that an active Module be stopped (unloaded)."""

    module_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilitiesListRequest:
    """Requests the list of registered capability definitions."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityExecuteRequest:
    """
    Requests execution of a capability by id through the generic
    compatibility/fallback endpoint (see
    `docs/guides/Running.md` section 12.3).
    """

    capability_id: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProvidersListRequest:
    """Requests the list of registered Providers."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfigGetRequest:
    """Requests a read-only view of the merged Configuration."""

    key: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReloadRequest:
    """
    Requests a reload of every active Module and a provider
    reconnect, mirroring the existing `/reload` slash command.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatRequest:
    """
    Requests one non-streaming chat turn.

    `session_id` is optional; when omitted, a new session is created
    for this single request and discarded (no persistence beyond the
    reply), matching a stateless "one-shot" chat call.
    """

    text: str
    session_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceTranscribeRequest:
    """
    Requests speech-to-text transcription only (no text pipeline).
    """

    audio_base64: str
    mime_type: str | None = None
    language: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceRespondRequest:
    """
    Requests one non-streaming chat turn from audio input: audio is
    transcribed (`voice.speech_to_text`) and the resulting text is
    submitted through the exact same path `ChatRequest` uses -- never
    a second reasoning pipeline. Deliberately never triggers
    text-to-speech itself (see `VoiceSpeakRequest`): the canonical
    response is always text first; speaking it is a separate,
    independently-controlled caller decision.
    """

    audio_base64: str
    mime_type: str | None = None
    language: str | None = None
    session_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceSpeakRequest:
    """
    Requests text-to-speech synthesis of already-known text (never the
    canonical text response's own generation -- that always happens
    through `ChatRequest`/`VoiceRespondRequest` first).

    `operation_id` is optional; a caller that wants to be able to stop
    this operation mid-synthesis via `VoiceStopSpeakingRequest` should
    supply one it generated itself (see
    `parika.modules.voice.operation_registry`).
    """

    text: str
    voice: str | None = None
    language: str | None = None
    operation_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceStopSpeakingRequest:
    """
    Requests cancellation of an in-progress `VoiceSpeakRequest`
    operation. Never affects PARIKA request processing or the
    canonical text response -- see
    `parika.modules.voice.operation_registry`'s module docstring.
    """

    operation_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceGetSettingsRequest:
    """
    Requests the current Voice language preference/availability
    summary (see `parika.modules.voice.language
    .VoiceLanguagePreferenceStore`). Read-only; has no fields.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseCreateRequest:
    """Requests creation of one new expense."""

    amount: Any
    item: str
    currency: str | None = None
    category: str | None = None
    date: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseGetRequest:
    """Requests one specific expense by id."""

    expense_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseListRequest:
    """Requests a filtered list of expenses."""

    period: str | None = None
    year: int | None = None
    month: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    category: str | None = None
    item: str | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseUpdateRequest:
    """
    Requests a partial update of one specific expense. `changes`
    contains only the fields the caller actually supplied (see
    `parika.tools.expense.driver.build_update_changes()`), so an
    omitted field always leaves that value unchanged.
    """

    expense_id: str
    changes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseDeleteRequest:
    """Requests deletion of one specific expense by id."""

    expense_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseSummarizeRequest:
    """Requests a deterministic total/breakdown for a filtered set of expenses."""

    period: str | None = None
    year: int | None = None
    month: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    category: str | None = None
    item: str | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    largest_count: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpenseCompareRequest:
    """Requests a deterministic comparison between two periods."""

    period_a: Mapping[str, Any]
    period_b: Mapping[str, Any]
    category: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VoiceUpdateSettingsRequest:
    """
    Requests a partial update of the current Voice language
    preference. An omitted field leaves that preference unchanged.
    Never affects an already in-flight `ChatRequest`/
    `VoiceRespondRequest` -- only the shared, current preference a
    later `VoiceSpeakRequest`/`VoiceTranscribeRequest` will resolve
    against (see `VoiceLanguagePreferenceStore`'s own docstring for
    why this is deliberately not a second output-preference
    mechanism).
    """

    input_language: str | None = None
    output_language: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaGetStateRequest:
    """
    Requests PARIKA's last known media playback state (see
    `parika.tools.media.state_store.MediaStateStore`). Read-only; has
    no fields. Never dispatches a command to the Web Client.
    """
