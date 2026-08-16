"""
PARIKA News Tool - Manifest

Defines the static Tool metadata describing the News Tool's three
Capabilities.

Like the Weather and Currency Tools, `news.latest`, `news.search`,
and `news.topic` are each registered as their own Tool
(`NewsToolDriver` bound to one `NewsMode` per instance), since
`ToolRequest` carries no capability identifier for a single Tool to
dispatch on. See `parika/tools/filesystem/manifest.py`'s module
docstring for the full reasoning.

This module owns Tool creation. ToolManager only registers and stores
the Tool instances produced here; it does not create Tool objects
itself.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from parika.core.tool_manager.tool import Tool

NEWS_TOOL_VERSION = "1.0.0"


class NewsMode(StrEnum):
    """
    The three Capabilities the News Tool implements.
    """

    LATEST = "latest"
    SEARCH = "search"
    TOPIC = "topic"


NEWS_CAPABILITY_LATEST = "news.latest"
NEWS_CAPABILITY_SEARCH = "news.search"
NEWS_CAPABILITY_TOPIC = "news.topic"

NEWS_TOOL_ID_LATEST = "tool.news_latest"
NEWS_TOOL_ID_SEARCH = "tool.news_search"
NEWS_TOOL_ID_TOPIC = "tool.news_topic"

_NEWS_RESULT_SEMANTICS = (
    "Returns articles/headlines. Summarize them naturally; do not "
    "describe raw tool output structures or list every field."
)
_NEWS_FAILURE_SEMANTICS = (
    "If no matching coverage is found, say so honestly rather than "
    "guessing."
)

NEWS_TOOL_AFFORDANCES: Mapping[str, Mapping[str, Any]] = {
    NEWS_CAPABILITY_LATEST: {
        "description": "Get the latest general news headlines.",
        "purpose": "Provides current general news headlines, since your own knowledge is not current.",
        "use_when": "the user asks for the latest general news or headlines, with no specific topic or query.",
        "avoid_when": "the request names a specific topic (use the Topic capability) or a specific query (use Search).",
        "requires": "nothing required; an optional maximum number of headlines.",
        "result_semantics": _NEWS_RESULT_SEMANTICS,
        "failure_semantics": _NEWS_FAILURE_SEMANTICS,
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of headlines to return.",
                },
            },
            "required": [],
        },
    },
    NEWS_CAPABILITY_SEARCH: {
        "description": "Search recent news coverage for a free-text query.",
        "purpose": "Provides current news coverage for any specific query, not limited to pre-configured topics.",
        "use_when": "the user asks for news about a specific subject that is not one of the dedicated topics.",
        "avoid_when": "the request is for general headlines with no query (use Latest) or names a dedicated topic (use Topic).",
        "requires": "a search query.",
        "result_semantics": _NEWS_RESULT_SEMANTICS,
        "failure_semantics": _NEWS_FAILURE_SEMANTICS,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of articles to return.",
                },
            },
            "required": ["query"],
        },
    },
    NEWS_CAPABILITY_TOPIC: {
        "description": (
            "Get the latest news headlines for one of these specific "
            "topics: world, business, technology, science, health, "
            "politics, sports, or entertainment."
        ),
        "purpose": "Provides dedicated current news coverage for a specific, well-known topic.",
        "use_when": (
            "the request is asking for the latest news/headlines on "
            "one of the topics above (e.g. 'latest technology news', "
            "'world news today', 'sports headlines') - prefer this "
            "over a generic web search or news search for these "
            "topics, since it returns dedicated news coverage."
        ),
        "avoid_when": "the subject is not one of the topics above (use Search instead).",
        "requires": "the topic name.",
        "result_semantics": _NEWS_RESULT_SEMANTICS,
        "failure_semantics": _NEWS_FAILURE_SEMANTICS,
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic name."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of headlines to return.",
                },
            },
            "required": ["topic"],
        },
    },
}
"""
Tool Affordance Contracts for `news.latest`/`news.search`/
`news.topic`, registered as each Capability's `CapabilityDefinition.
metadata["tool_affordance"]` (see `parika/modules/news/driver.py`).
"""


def create_news_latest_tool() -> Tool:
    """
    Build the immutable Tool descriptor for `news.latest`.
    """

    return Tool(
        id=NEWS_TOOL_ID_LATEST,
        name="News Latest",
        version=NEWS_TOOL_VERSION,
        description=(
            "Returns the latest headlines from PARIKA's configured "
            "general news feeds."
        ),
        capabilities=(NEWS_CAPABILITY_LATEST,),
    )


def create_news_search_tool() -> Tool:
    """
    Build the immutable Tool descriptor for `news.search`.
    """

    return Tool(
        id=NEWS_TOOL_ID_SEARCH,
        name="News Search",
        version=NEWS_TOOL_VERSION,
        description=(
            "Searches recent news coverage for a free-text query, "
            "for any topic - not only pre-configured ones."
        ),
        capabilities=(NEWS_CAPABILITY_SEARCH,),
    )


def create_news_topic_tool() -> Tool:
    """
    Build the immutable Tool descriptor for `news.topic`.
    """

    return Tool(
        id=NEWS_TOOL_ID_TOPIC,
        name="News Topic",
        version=NEWS_TOOL_VERSION,
        description=(
            "Returns the latest headlines for a specific topic (e.g. "
            "world, business, technology, science, health, "
            "politics, sports, entertainment), falling back to a "
            "general search when the topic has no dedicated feed."
        ),
        capabilities=(NEWS_CAPABILITY_TOPIC,),
    )
