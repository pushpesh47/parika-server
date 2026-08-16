"""
PARIKA Memory Tool - Manifest

Defines the static Tool metadata describing the Memory Tool's three
Capabilities: `memory.remember`, `memory.search`, `memory.forget`.

Advertising these as native, model-callable tools (rather than
hardcoding responses to specific questions) is what lets PARIKA
satisfy the "truthful memory responses" requirement architecturally
(Phase 1 Completion Specification sections 1, 11): the model's own
reply is generated only after it sees this tool's real result, so a
success/failure claim about "remembering" something is only ever as
truthful as the actual `MemoryManager.remember()` call that produced
it -- see `driver.py`.

Like the Filesystem/Weather Tools, each Capability is its own Tool
(`MemoryToolDriver` bound to one `MemoryToolOperation` per instance),
since `ToolRequest` carries no capability identifier for a single Tool
to dispatch on.
"""

from __future__ import annotations

from typing import Any, Mapping

from parika.core.tool_manager.tool import Tool

MEMORY_TOOL_VERSION = "1.0.0"

MEMORY_CAPABILITY_REMEMBER = "memory.remember"
MEMORY_CAPABILITY_SEARCH = "memory.search"
MEMORY_CAPABILITY_FORGET = "memory.forget"

MEMORY_TOOL_ID_REMEMBER = "tool.memory_remember"
MEMORY_TOOL_ID_SEARCH = "tool.memory_search"
MEMORY_TOOL_ID_FORGET = "tool.memory_forget"

MEMORY_TOOL_AFFORDANCES: Mapping[str, Mapping[str, Any]] = {
    MEMORY_CAPABILITY_REMEMBER: {
        "description": (
            "Permanently remember a fact, preference, or other piece of "
            "information about the user, so it can be recalled in any "
            "future conversation - not just this one."
        ),
        "purpose": (
            "Provides durable storage of a fact or preference the user "
            "wants recalled in future conversations, beyond this one."
        ),
        "use_when": (
            "the user explicitly asks you to remember, save, store, "
            "note, or not forget something (e.g. 'remember that...', "
            "'save this', \"don't forget...\")."
        ),
        "avoid_when": (
            "the user made an ordinary statement, question, greeting, "
            "or general conversation without asking you to remember it "
            "- stating a fact or preference in passing is not by "
            "itself a request to remember it; or the information is "
            "about your own identity (your name, nickname, full name, "
            "creator, organization, purpose, description, version, "
            "provider, or model) - that already comes from Assistant "
            "Identity above, never from memory."
        ),
        "requires": (
            "the exact information the user asked to remember; ask a "
            "follow-up question if what to remember is unclear."
        ),
        "result_semantics": (
            "Confirms the fact was stored. Only report that you "
            "remembered something after this tool actually returns "
            "success in this same turn - never claim to remember "
            "something you have not actually stored with this tool."
        ),
        "failure_semantics": (
            "If storing fails, say so plainly without exposing "
            "internal exception details."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": (
                        "The exact information the user asked to remember, "
                        "as a clear standalone statement - nothing more. "
                        "Never include surrounding conversation, your own "
                        "reply, other unrelated sentences, or inferred/"
                        "expanded wording. If the user asked you to "
                        "remember only part of a longer message (e.g. "
                        "'remember only the second sentence'), include "
                        "only that part."
                    ),
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Optional category: profile, preference, relationship, "
                        "goal, project, skill, fact, reminder_reference, or "
                        "custom. Leave unset to let PARIKA infer it automatically."
                    ),
                },
                "importance": {
                    "type": "string",
                    "description": "Optional importance: critical, high, normal, or low.",
                },
            },
            "required": ["content"],
        },
    },
    MEMORY_CAPABILITY_SEARCH: {
        "description": "Search permanently remembered facts and preferences about the user.",
        "purpose": "Provides access to durably remembered facts/preferences not already in this turn's context.",
        "use_when": (
            "something the user asks about might already be "
            "remembered but is not already present in the 'Relevant "
            "permanent memories about the user' section already "
            "injected into this context, if any."
        ),
        "avoid_when": (
            "the requested information is already present in that "
            "injected section above, is about your own identity "
            "(already available from Assistant Identity), or concerns "
            "this current conversation itself rather than a "
            "previously remembered fact."
        ),
        "requires": "a search query.",
        "result_semantics": "Returns matching remembered facts; state them naturally.",
        "failure_semantics": "If nothing matches, say so honestly rather than guessing.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text."},
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matches to return.",
                },
            },
            "required": ["query"],
        },
    },
    MEMORY_CAPABILITY_FORGET: {
        "description": (
            "Permanently forget a previously remembered fact or "
            "preference about the user, when they explicitly ask you to "
            "forget or correct something."
        ),
        "purpose": "Provides the ability to remove a previously remembered fact that is no longer accurate or wanted.",
        "use_when": "the user explicitly asks you to forget or correct a previously remembered fact.",
        "avoid_when": "no explicit forget/correction request was made.",
        "requires": "enough detail (a description or exact memory id) to identify which memory to remove.",
        "result_semantics": "Confirms removal. Only report success after this tool actually returns success.",
        "failure_semantics": "If nothing matching is found, say so plainly.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text describing which remembered fact to forget.",
                },
                "memory_id": {
                    "type": "string",
                    "description": "Exact memory id to forget, if already known.",
                },
            },
            "required": [],
        },
    },
}
"""
Tool Affordance Contracts for `memory.remember`/`memory.search`/
`memory.forget`, registered as each Capability's `CapabilityDefinition.
metadata["tool_affordance"]` (see `parika/modules/memory/driver.py`).
This is where every memory-specific behavioral rule now lives -- see
`parika/interfaces/ai_context/behavior.py`'s module docstring for why
none of this lives in AI Context Engineering itself.
"""

MEMORY_IDENTITY_SENSITIVE_CAPABILITIES: frozenset[str] = frozenset(
    {MEMORY_CAPABILITY_REMEMBER, MEMORY_CAPABILITY_SEARCH, MEMORY_CAPABILITY_FORGET}
)
"""
Every Memory Capability that must never be advertised for a turn AI
Context Engineering recognizes as an Assistant Identity question (see
`tools/memory/identity_guard.is_identity_query()`). Registered as each
Capability's `CapabilityDefinition.metadata["identity_sensitive"]` (see
`parika/modules/memory/driver.py`) -- a generic flag AI Context
Engineering checks without knowing it names a "memory" capability at
all (see `parika/interfaces/ai_context/tool_context.py`).
"""


def create_memory_remember_tool() -> Tool:
    """Build the immutable Tool descriptor for `memory.remember`."""

    return Tool(
        id=MEMORY_TOOL_ID_REMEMBER,
        name="Memory Remember",
        version=MEMORY_TOOL_VERSION,
        description=(
            "Permanently remembers a fact, preference, or other piece "
            "of information about the user, so it can be recalled in "
            "any future conversation."
        ),
        capabilities=(MEMORY_CAPABILITY_REMEMBER,),
    )


def create_memory_search_tool() -> Tool:
    """Build the immutable Tool descriptor for `memory.search`."""

    return Tool(
        id=MEMORY_TOOL_ID_SEARCH,
        name="Memory Search",
        version=MEMORY_TOOL_VERSION,
        description=(
            "Searches permanently remembered facts and preferences "
            "about the user."
        ),
        capabilities=(MEMORY_CAPABILITY_SEARCH,),
    )


def create_memory_forget_tool() -> Tool:
    """Build the immutable Tool descriptor for `memory.forget`."""

    return Tool(
        id=MEMORY_TOOL_ID_FORGET,
        name="Memory Forget",
        version=MEMORY_TOOL_VERSION,
        description=(
            "Permanently forgets a previously remembered fact or "
            "preference about the user."
        ),
        capabilities=(MEMORY_CAPABILITY_FORGET,),
    )
