"""
Unit tests for `parika.providers.ollama.tool_calling.ToolCallResolver`.
"""

from __future__ import annotations

import json

from parika.core.logger.logger import Logger
from parika.core.configuration.configuration import Configuration
from parika.providers.ollama.messages import OllamaToolCall, OllamaToolSpec
from parika.providers.ollama.tool_calling import ToolCallResolver

KNOWN_SPEC = OllamaToolSpec(
    name="web_search",
    description="Search the web.",
    capability_id="web.search",
    parameters={"type": "object", "properties": {}},
)

OTHER_SPEC = OllamaToolSpec(
    name="get_current_datetime",
    description="Get the current date and time.",
    capability_id="runtime.current_datetime",
    parameters={"type": "object", "properties": {}},
)

TOOLS_BY_NAME = {
    KNOWN_SPEC.name: KNOWN_SPEC,
    OTHER_SPEC.name: OTHER_SPEC,
}


class TestUnknownToolRecovery:
    """
    Priority 4: when the model hallucinates a tool name it was never
    actually offered, the resolver reports every tool name that *is*
    available - generically, never any hardcoded name - as ordinary
    tool-calling protocol feedback (a "tool" role message), so the
    model can self-correct on its next turn.
    """

    def test_unknown_tool_lists_every_available_tool_name(self) -> None:
        resolver = ToolCallResolver(logger=Logger(Configuration()))

        content, capability_id, succeeded = resolver.resolve(
            OllamaToolCall(name="lookup_weather", arguments={}),
            TOOLS_BY_NAME,
        )

        payload = json.loads(content)

        assert succeeded is False
        assert capability_id is None
        assert payload["error"] == "Unknown tool 'lookup_weather'."
        assert payload["available_tools"] == [
            "get_current_datetime",
            "web_search",
        ]

    def test_unknown_tool_with_no_tools_offered_reports_empty_list(
        self,
    ) -> None:
        resolver = ToolCallResolver(logger=Logger(Configuration()))

        content, capability_id, succeeded = resolver.resolve(
            OllamaToolCall(name="anything", arguments={}), {}
        )

        payload = json.loads(content)

        assert succeeded is False
        assert capability_id is None
        assert payload["available_tools"] == []

    def test_unbound_resolver_reports_unavailable_without_raising(
        self,
    ) -> None:
        resolver = ToolCallResolver(logger=Logger(Configuration()))

        content, capability_id, succeeded = resolver.resolve(
            OllamaToolCall(name="web_search", arguments={"query": "x"}),
            TOOLS_BY_NAME,
        )

        payload = json.loads(content)

        assert succeeded is False
        assert capability_id == "web.search"
        assert "no Brain is bound" in payload["error"]
        assert resolver.is_bound is False
