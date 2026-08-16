"""
PARIKA API - Capabilities Handler

`handle_capability_execute` is the generic compatibility/fallback
endpoint's handler (see `docs/guides/Running.md` section 12.3). It
resolves a capability id to its implementing Tool using *exactly* the
same selection rule Planner itself already uses for Tool-backed
capabilities (`Planner._select_tool()`: the lowest-`id`, enabled Tool
whose `capabilities` tuple contains the requested capability id) --
translation of an existing decision, never a new one.

Provider-backed capabilities (e.g. `chat.respond`) have no Tool to
select and are not supported by this generic endpoint; callers are
directed to the dedicated `/api/v1/chat` endpoint instead.
"""

from __future__ import annotations

from typing import Any

from parika.core.tool_manager.request import ToolRequest
from parika.interfaces.runtime import ParikaRuntime

from ..requests import CapabilitiesListRequest, CapabilityExecuteRequest


def handle_capabilities_list(
    runtime: ParikaRuntime, request: CapabilitiesListRequest
) -> list[dict[str, Any]]:
    """
    Return every registered capability definition, mirroring
    `/capabilities`.
    """

    return [
        {
            "id": definition.id,
            "name": definition.name,
            "description": definition.description,
            "category": definition.category.value,
            "enabled": definition.enabled,
        }
        for definition in sorted(
            runtime.capability_registry.get_all(), key=lambda item: item.id
        )
    ]


def handle_capability_execute(
    runtime: ParikaRuntime, request: CapabilityExecuteRequest
) -> dict[str, Any]:
    """
    Execute a capability by id through its implementing Tool.

    Raises:
        CapabilityNotFoundError:
            If no capability with this id is registered (mapped to
            HTTP 404).

        NotImplementedError:
            If the capability is registered but is provider-backed
            (no Tool implements it) -- this generic endpoint supports
            only Tool-backed capabilities; provider-backed
            capabilities (chat) have their own dedicated endpoint
            (mapped to HTTP 501).
    """

    # Validates the capability itself exists -- raises
    # CapabilityNotFoundError (-> 404) exactly as CapabilityRegistry
    # already does for any other caller.
    runtime.capability_registry.get(request.capability_id)

    candidates = sorted(
        (
            tool
            for tool in runtime.tool_manager.get_all()
            if tool.enabled and request.capability_id in tool.capabilities
        ),
        key=lambda tool: tool.id,
    )

    if not candidates:
        raise NotImplementedError(
            f"Capability '{request.capability_id}' is not backed by a "
            "Tool and cannot be executed through the generic "
            "capabilities/{id}/execute endpoint. If this is a chat/LLM "
            "capability, use POST /api/v1/chat instead."
        )

    tool = candidates[0]

    response = runtime.tool_manager.execute(
        tool.id,
        ToolRequest(
            arguments=request.arguments,
            parameters=request.parameters,
        ),
    )

    return {
        "capability_id": request.capability_id,
        "result": response.result,
        "attributes": dict(response.attributes),
    }
