"""
Tests that every `Route` registered by `register_router_bindings()`
actually dispatches through the existing, unmodified `Router` Core
component (section 6.3).
"""

from __future__ import annotations

from parika.api import requests
from parika.api.router_bindings import register_router_bindings
from parika.api.session_registry import build_default_session_store
from parika.core.router.router import Router


def test_every_binding_dispatches(runtime_factory) -> None:
    runtime = runtime_factory()
    session_store = build_default_session_store(runtime)
    router = Router(event_bus=runtime.event_bus, logger=runtime.logger)

    register_router_bindings(router, runtime, session_store)

    # 15 pre-existing routes + `voice.get_settings`/`voice.update_settings`
    # (this Module's additive Voice language-preference settings endpoint)
    # + the 7 Expense Management routes (create/get/list/update/delete/
    # summarize/compare) + `media.get_state` (the Media Capability's
    # read-only state snapshot endpoint).
    assert router.count() == 25

    status_result = router.dispatch(requests.StatusRequest())
    assert "lifecycle_state" in status_result

    tools_result = router.dispatch(requests.ToolsListRequest())
    assert isinstance(tools_result, list)

    capabilities_result = router.dispatch(requests.CapabilitiesListRequest())
    assert isinstance(capabilities_result, list)

    providers_result = router.dispatch(requests.ProvidersListRequest())
    assert isinstance(providers_result, list)

    config_result = router.dispatch(requests.ConfigGetRequest())
    assert config_result["key"] is None

    chat_result = router.dispatch(requests.ChatRequest(text="hello"))
    assert "session_id" in chat_result


def test_high_frequency_polling_routes_are_registered_as_log_dispatch_false(
    runtime_factory,
) -> None:
    """
    Router request/response log-noise suppression (see
    `Route.log_dispatch`) is applied here, at registration, rather
    than inside `Router` itself -- `Router` stays generic and knows
    nothing about which route ids are "high-frequency polling" ones.
    """

    runtime = runtime_factory()
    session_store = build_default_session_store(runtime)
    router = Router(event_bus=runtime.event_bus, logger=runtime.logger)

    register_router_bindings(router, runtime, session_store)

    quiet_route_ids = {
        "status.get",
        "providers.list",
        "config.get",
        "voice.get_settings",
        "media.get_state",
        "expense.list",
        "expense.summarize",
    }

    for route_id in quiet_route_ids:
        assert router.get(route_id).log_dispatch is False

    # Every other route keeps the default, unchanged behavior.
    for route in router.get_all():
        if route.id not in quiet_route_ids:
            assert route.log_dispatch is True
