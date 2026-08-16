"""
PARIKA Web Search Tool - Manifest

Defines the static Tool metadata describing the Web Search Tool,
including its `WEB_SEARCH_TOOL_AFFORDANCE` -- the Tool Affordance
Contract (purpose, use/avoid guidance, requirements, result/failure
semantics, and JSON Schema parameters) AI Context Engineering
advertises for this capability. The Web Search Tool owns this contract
entirely; AI Context Engineering only ever discovers and assembles it
(see `parika/interfaces/ai_context/tool_context.py`) -- it never
defines or hardcodes it.

This module owns Tool creation. ToolManager only registers and stores
the Tool instance produced here; it does not create Tool objects
itself.
"""

from __future__ import annotations

from typing import Any, Mapping

from parika.core.tool_manager.tool import Tool

WEB_SEARCH_CAPABILITY_ID = "web.search"
"""
Identifier of the Capability implemented by this Tool.
"""

WEB_SEARCH_TOOL_ID = "tool.web_search"
"""
Identifier of the Tool registered with ToolManager.
"""

WEB_SEARCH_TOOL_VERSION = "1.0.0"

WEB_SEARCH_TOOL_AFFORDANCE: Mapping[str, Any] = {
    "description": (
        "Search the web and return relevant results. Works for any "
        "topic - technology, science, sports, politics, finance, "
        "products, or anything else - not just news."
    ),
    "purpose": (
        "Provides access to current, external, or specific "
        "information not already known -- your own knowledge is "
        "frozen at training time and does not include recent events."
    ),
    "use_when": (
        "the user needs current, external, or unfamiliar information "
        "that is not already available from Assistant Identity, the "
        "current conversation, injected Memory, injected Knowledge, "
        "or an earlier Tool result."
    ),
    "avoid_when": (
        "the answer is already available from an earlier source in "
        "that order, or the question is about your own identity."
    ),
    "requires": (
        "a search query capturing what to look for; ask the user to "
        "clarify if the request is too vague to form one."
    ),
    "result_semantics": (
        "Returns a list of web results (titles, snippets, URLs, and "
        "optionally extracted page content). Summarize the relevant "
        "findings in natural language; do not describe the raw result "
        "structure or list every field."
    ),
    "failure_semantics": (
        "If the search fails or returns nothing relevant, say so "
        "honestly rather than guessing an answer."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search query text. Preserve any year or date the "
                    "user explicitly mentioned, exactly as given (e.g. "
                    "keep '2025' if the user wrote '2025', keep '2026' "
                    "if the user wrote '2026'). Never invent, assume, "
                    "or default to a year the user did not mention - "
                    "in particular, never substitute a year you "
                    "remember from training data. If the user did not "
                    "mention a year at all, do not add one - the "
                    "search results are already ordered by relevance "
                    "and recency without it. If you need today's exact "
                    "date to resolve a relative timeframe (e.g. 'this "
                    "week'), call get_current_datetime first and use "
                    "its result - never guess it."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "Maximum number of results to return. Prefer a "
                    "higher value (e.g. 10) for broad or ambiguous "
                    "queries so relevant results are not discarded."
                ),
            },
        },
        "required": ["query"],
    },
}
"""
The Tool Affordance Contract for `web.search`, registered as this
Capability's `CapabilityDefinition.metadata["tool_affordance"]` (see
`parika/modules/web_search/driver.py`). AI Context Engineering reads
this generically; it never mentions `web.search` or this contract by
name anywhere in its own code.
"""


def create_web_search_tool() -> Tool:
    """
    Build the immutable Tool descriptor for the Web Search Tool.

    Returns:
        A Tool ready to be registered with ToolManager alongside a
        WebSearchToolDriver instance.
    """

    return Tool(
        id=WEB_SEARCH_TOOL_ID,
        name="Web Search",
        version=WEB_SEARCH_TOOL_VERSION,
        description=(
            "Searches the web and optionally fetches and extracts "
            "the readable content of each result page."
        ),
        capabilities=(WEB_SEARCH_CAPABILITY_ID,),
    )
