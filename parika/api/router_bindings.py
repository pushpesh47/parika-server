"""
PARIKA API - Router Bindings

Registers one `Route` per internal operation on the existing, frozen
`Router` Core component (`parika/core/router/router.py`), which had
zero production call sites before the Server Platform (see
`docs/guides/Running.md` section 12) started using it.

This is the *only* place `Router.register_route()` is called by the
API layer. Every FastAPI route handler in `parika/api/routers/`
dispatches through the bound `Router` instance
(`request.app.state.router.dispatch(...)`) rather than calling a Core
manager directly.

No change is made to `Router`'s dispatch/registry behavior, exceptions,
or events. The only Core addition is `Route.log_dispatch` (default
`True`, unchanged for every route below except the explicitly marked
high-frequency polling routes) -- see its own docstring.
"""

from __future__ import annotations

from parika.core.router.route import Route
from parika.core.router.router import Router
from parika.interfaces.runtime import ParikaRuntime
from parika.interfaces.session_store import SqliteSessionStore

from . import requests
from .handlers import (
    capabilities,
    chat,
    config,
    expense,
    media,
    modules,
    providers,
    status,
    tools,
    voice,
)


def register_router_bindings(
    router: Router,
    runtime: ParikaRuntime,
    session_store: SqliteSessionStore,
) -> None:
    """
    Register every API-layer `Route` on `router`.

    Idempotent within one process lifetime is not required (this is
    called exactly once, during server startup, from
    `parika/server/app.py`'s `lifespan` handler); calling it twice
    against the same `Router` instance would raise
    `RouteAlreadyRegisteredError`, exactly as `Router` already
    documents.
    """

    bindings: tuple[Route, ...] = (
        Route(
            id="status.get",
            matcher=lambda request: isinstance(request, requests.StatusRequest),
            handler=lambda request: status.handle_status(runtime, request),
            description="Aggregate runtime status snapshot (mirrors /status).",
            # High-frequency status/health-monitoring polling target --
            # see `Route.log_dispatch`'s own docstring.
            log_dispatch=False,
        ),
        Route(
            id="tools.list",
            matcher=lambda request: isinstance(request, requests.ToolsListRequest),
            handler=lambda request: tools.handle_tools_list(runtime, request),
            description="List every registered Tool (mirrors /tools).",
        ),
        Route(
            id="modules.list",
            matcher=lambda request: isinstance(request, requests.ModulesListRequest),
            handler=lambda request: modules.handle_modules_list(runtime, request),
            description="List every registered Module (mirrors /modules).",
        ),
        Route(
            id="modules.start",
            matcher=lambda request: isinstance(request, requests.ModuleStartRequest),
            handler=lambda request: modules.handle_module_start(runtime, request),
            description="Start (load) a registered Module.",
        ),
        Route(
            id="modules.stop",
            matcher=lambda request: isinstance(request, requests.ModuleStopRequest),
            handler=lambda request: modules.handle_module_stop(runtime, request),
            description="Stop (unload) an active Module.",
        ),
        Route(
            id="capabilities.list",
            matcher=lambda request: isinstance(request, requests.CapabilitiesListRequest),
            handler=lambda request: capabilities.handle_capabilities_list(runtime, request),
            description="List every registered capability (mirrors /capabilities).",
        ),
        Route(
            id="capabilities.execute",
            matcher=lambda request: isinstance(request, requests.CapabilityExecuteRequest),
            handler=lambda request: capabilities.handle_capability_execute(runtime, request),
            description=(
                "Generic compatibility/fallback capability execution "
                "endpoint (see docs/guides/Running.md section 12.3) "
                "-- prefer a dedicated domain-specific endpoint when "
                "one exists."
            ),
        ),
        Route(
            id="providers.list",
            matcher=lambda request: isinstance(request, requests.ProvidersListRequest),
            handler=lambda request: providers.handle_providers_list(runtime, request),
            description="List every registered Provider (mirrors /providers).",
            # High-frequency status/health-monitoring polling target --
            # see `Route.log_dispatch`'s own docstring.
            log_dispatch=False,
        ),
        Route(
            id="config.get",
            matcher=lambda request: isinstance(request, requests.ConfigGetRequest),
            handler=lambda request: config.handle_config_get(runtime, request),
            description="Read-only Configuration view (mirrors /config).",
            # High-frequency status/health-monitoring polling target --
            # see `Route.log_dispatch`'s own docstring.
            log_dispatch=False,
        ),
        Route(
            id="reload.modules",
            matcher=lambda request: isinstance(request, requests.ReloadRequest),
            handler=lambda request: config.handle_reload(runtime, request),
            description="Reload active Modules and reconnect Providers (mirrors /reload).",
        ),
        Route(
            id="expense.create",
            matcher=lambda request: isinstance(request, requests.ExpenseCreateRequest),
            handler=lambda request: expense.handle_create_expense(runtime, request),
            description="Add a new expense (mirrors expense.add_expense).",
        ),
        Route(
            id="expense.get",
            matcher=lambda request: isinstance(request, requests.ExpenseGetRequest),
            handler=lambda request: expense.handle_get_expense(runtime, request),
            description="Retrieve one expense by id (mirrors expense.get_expense).",
        ),
        Route(
            id="expense.list",
            matcher=lambda request: isinstance(request, requests.ExpenseListRequest),
            handler=lambda request: expense.handle_list_expenses(runtime, request),
            description="List/filter expenses (mirrors expense.list_expenses).",
            # High-frequency reload target --
            # see `Route.log_dispatch`'s own docstring.
            log_dispatch=False,
        ),
        Route(
            id="expense.update",
            matcher=lambda request: isinstance(request, requests.ExpenseUpdateRequest),
            handler=lambda request: expense.handle_update_expense(runtime, request),
            description="Partially update one specific expense by id.",
        ),
        Route(
            id="expense.delete",
            matcher=lambda request: isinstance(request, requests.ExpenseDeleteRequest),
            handler=lambda request: expense.handle_delete_expense(runtime, request),
            description="Delete one specific expense by id.",
        ),
        Route(
            id="expense.summarize",
            matcher=lambda request: isinstance(request, requests.ExpenseSummarizeRequest),
            handler=lambda request: expense.handle_summarize_expenses(runtime, request),
            description="Deterministic total/breakdown for a filtered set of expenses.",
            # High-frequency reload target --
            # see `Route.log_dispatch`'s own docstring.
            log_dispatch=False,
        ),
        Route(
            id="expense.compare",
            matcher=lambda request: isinstance(request, requests.ExpenseCompareRequest),
            handler=lambda request: expense.handle_compare_expenses(runtime, request),
            description="Deterministic comparison between two periods.",
        ),
        Route(
            id="chat.respond",
            matcher=lambda request: isinstance(request, requests.ChatRequest),
            handler=lambda request: chat.handle_chat(runtime, session_store, request),
            description="One non-streaming chat turn, via Planner/Brain.",
        ),
        Route(
            id="voice.transcribe",
            matcher=lambda request: isinstance(request, requests.VoiceTranscribeRequest),
            handler=lambda request: voice.handle_voice_transcribe(runtime, request),
            description="Speech-to-text transcription only (audio -> text).",
        ),
        Route(
            id="voice.respond",
            matcher=lambda request: isinstance(request, requests.VoiceRespondRequest),
            handler=lambda request: voice.handle_voice_respond(
                runtime, session_store, request
            ),
            description=(
                "audio -> speech_to_text -> the same chat.respond text "
                "pipeline -> canonical text response (never speaks the "
                "reply itself)."
            ),
        ),
        Route(
            id="voice.speak",
            matcher=lambda request: isinstance(request, requests.VoiceSpeakRequest),
            handler=lambda request: voice.handle_voice_speak(runtime, request),
            description="Text-to-speech synthesis of already-known text.",
        ),
        Route(
            id="voice.stop_speaking",
            matcher=lambda request: isinstance(
                request, requests.VoiceStopSpeakingRequest
            ),
            handler=lambda request: voice.handle_voice_stop_speaking(runtime, request),
            description="Cancel an in-progress text-to-speech operation.",
        ),
        Route(
            id="voice.get_settings",
            matcher=lambda request: isinstance(
                request, requests.VoiceGetSettingsRequest
            ),
            handler=lambda request: voice.handle_voice_get_settings(runtime, request),
            description=(
                "Read the current Voice language preference/availability "
                "summary."
            ),
            # High-frequency status/health-monitoring polling target --
            # see `Route.log_dispatch`'s own docstring.
            log_dispatch=False,
        ),
        Route(
            id="voice.update_settings",
            matcher=lambda request: isinstance(
                request, requests.VoiceUpdateSettingsRequest
            ),
            handler=lambda request: voice.handle_voice_update_settings(
                runtime, request
            ),
            description="Update the current Voice language preference.",
        ),
        Route(
            id="media.get_state",
            matcher=lambda request: isinstance(request, requests.MediaGetStateRequest),
            handler=lambda request: media.handle_media_get_state(runtime, request),
            description="Read PARIKA's last known media playback state.",
            # High-frequency status/health-monitoring polling target --
            # see `Route.log_dispatch`'s own docstring.
            log_dispatch=False,
        ),
    )

    for route in bindings:
        router.register_route(route)
