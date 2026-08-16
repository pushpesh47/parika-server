"""
PARIKA Memory Tool - Driver

Implements the `ToolDriver` contract for `memory.remember`,
`memory.search`, and `memory.forget`, calling the injected
`MemoryManager` for real -- this driver never fabricates a result: a
`memory.remember` call only ever reports success after
`MemoryManager.remember()` genuinely persisted the memory (see
`manifest.py`'s module docstring for why this is what makes "truthful
memory responses" architectural rather than a hardcoded response).

A single `MemoryToolDriver` instance is bound to exactly one
`MemoryToolOperation` at construction time (see `manifest.py`), like
the Filesystem/Weather Tools.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from parika.core.memory_manager.memory_category import MemoryCategory
from parika.core.memory_manager.memory_importance import MemoryImportance
from parika.core.memory_manager.memory_manager import MemoryManager
from parika.core.memory_manager.memory_search_query import MemorySearchQuery
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse

from .categorization import categorize
from .exceptions import InvalidMemoryToolArgumentError
from .identity_guard import build_identity_terms, is_assistant_identity_content

if TYPE_CHECKING:
    from parika.core.configuration.configuration import Configuration

DEFAULT_SEARCH_LIMIT = 5

_INSTRUCTION_PREFIX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^\s*(?:please\s+)?(?:remember|save|store|note)\b\s*"
        r"(?:that\b|this\b)?[:,]?\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*don'?t\s+forget\b\s*(?:that\b|this\b)?[:,]?\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*add\s+(?:this|that)\s+to\s+memory[:,]?\s*",
        re.IGNORECASE,
    ),
)
"""
Defensive normalization patterns stripping a leading explicit-memory
instruction phrase (e.g. "remember that ", "save this: ", "don't
forget ") from `content` before it is stored, so the memory itself
never carries the instruction verb the user used to trigger it - only
the actual information (PARIKA Memory Subsystem Refactor Requirement
C, "Precision Storage"). The model is separately instructed (see this
Tool's own `manifest.MEMORY_TOOL_AFFORDANCES[MEMORY_CAPABILITY_REMEMBER]`
description) to already pass precise content without such a prefix;
this is a deterministic backstop for when it does not.
"""


def _strip_instruction_prefix(content: str) -> str:
    """
    Strip a single leading explicit-memory instruction phrase from
    `content`, if present. Only ever removes a *prefix*; never touches
    the remainder of the text, and never strips anything if doing so
    would leave nothing behind.
    """

    for pattern in _INSTRUCTION_PREFIX_PATTERNS:
        stripped = pattern.sub("", content, count=1).strip()

        if stripped and stripped != content.strip():
            return stripped

    return content.strip()


class MemoryToolOperation(StrEnum):
    """The three Capabilities the Memory Tool implements."""

    REMEMBER = "remember"
    SEARCH = "search"
    FORGET = "forget"


class MemoryToolDriver:
    """ToolDriver implementing one Memory Tool operation."""

    def __init__(
        self,
        operation: MemoryToolOperation,
        *,
        memory_manager: MemoryManager,
        configuration: "Configuration | None" = None,
    ) -> None:
        """
        Parameters
        ----------
        operation:
            Which of the three Memory Tool Capabilities this driver
            instance implements.

        memory_manager:
            The MemoryManager to delegate real persistence to.

        configuration:
            Optional Configuration used to build the Assistant
            Identity protection terms consulted by
            `_execute_remember()` (see `identity_guard.py`). Existing
            call sites that omit this argument are unaffected: identity
            protection then relies solely on the provider-agnostic
            self-referential patterns in `identity_guard.py`, still
            active unconditionally.
        """

        self._operation = operation
        self._memory_manager = memory_manager
        self._identity_terms = build_identity_terms(configuration)

    def execute(self, request: ToolRequest) -> ToolResponse:
        match self._operation:
            case MemoryToolOperation.REMEMBER:
                return self._execute_remember(request)
            case MemoryToolOperation.SEARCH:
                return self._execute_search(request)
            case MemoryToolOperation.FORGET:
                return self._execute_forget(request)

        raise InvalidMemoryToolArgumentError(
            f"Unknown memory tool operation: {self._operation!r}."
        )

    def _execute_remember(self, request: ToolRequest) -> ToolResponse:
        content = request.arguments.get("content")

        if not isinstance(content, str) or not content.strip():
            raise InvalidMemoryToolArgumentError(
                "request.arguments['content'] must be a non-empty string."
            )

        content = _strip_instruction_prefix(content)

        # Assistant Identity Protection (PARIKA Memory Subsystem
        # Refactor Requirement A): this check runs unconditionally,
        # for every provider/model, regardless of how the tool-spec
        # description instructed the model - see `identity_guard.py`.
        # Content flagged here is never persisted; the call still
        # succeeds (no exception) so the model sees a clear, truthful
        # "not stored" result rather than an error.
        if is_assistant_identity_content(content, self._identity_terms):
            return ToolResponse(
                result={
                    "stored": False,
                    "created": False,
                    "reason": "assistant_identity_protected",
                    "detail": (
                        "Assistant identity is owned by Configuration, "
                        "not Memory, and is never stored."
                    ),
                },
                attributes={"content": content},
            )

        raw_category = request.arguments.get("category")
        category = (
            MemoryCategory(str(raw_category).lower())
            if raw_category
            else categorize(content)
        )

        raw_importance = request.arguments.get("importance")
        importance = (
            MemoryImportance(str(raw_importance).lower())
            if raw_importance
            else MemoryImportance.NORMAL
        )

        memory, created = self._memory_manager.remember(
            content=content, category=category, importance=importance
        )

        return ToolResponse(
            result={
                "stored": True,
                "created": created,
                "memory_id": memory.memory_id,
                "category": memory.category.value,
                "importance": memory.importance.value,
            },
            attributes={"content": content},
        )

    def _execute_search(self, request: ToolRequest) -> ToolResponse:
        query = request.arguments.get("query")

        if not isinstance(query, str) or not query.strip():
            raise InvalidMemoryToolArgumentError(
                "request.arguments['query'] must be a non-empty string."
            )

        raw_limit: Any = request.arguments.get("limit", DEFAULT_SEARCH_LIMIT)
        limit = int(raw_limit) if raw_limit else DEFAULT_SEARCH_LIMIT

        results = self._memory_manager.search(
            MemorySearchQuery(text=query, limit=limit)
        )

        return ToolResponse(
            result={
                "matches": [
                    {
                        "memory_id": scored.memory.memory_id,
                        "content": scored.memory.content,
                        "category": scored.memory.category.value,
                        "importance": scored.memory.importance.value,
                        "confidence": scored.memory.confidence,
                    }
                    for scored in results
                ]
            },
            attributes={"query": query, "match_count": len(results)},
        )

    def _execute_forget(self, request: ToolRequest) -> ToolResponse:
        memory_id = request.arguments.get("memory_id")
        query = request.arguments.get("query")

        if memory_id:
            if self._memory_manager.contains(str(memory_id)):
                forgotten = self._memory_manager.forget(str(memory_id))
                return ToolResponse(
                    result={"forgotten": True, "memory_id": forgotten.memory_id}
                )

            return ToolResponse(result={"forgotten": False, "reason": "not_found"})

        if not isinstance(query, str) or not query.strip():
            raise InvalidMemoryToolArgumentError(
                "request.arguments must include either 'memory_id' or 'query'."
            )

        matches = self._memory_manager.search(MemorySearchQuery(text=query, limit=1))

        if not matches:
            return ToolResponse(result={"forgotten": False, "reason": "not_found"})

        forgotten = self._memory_manager.forget(matches[0].memory.memory_id)

        return ToolResponse(
            result={
                "forgotten": True,
                "memory_id": forgotten.memory_id,
                "content": forgotten.content,
            }
        )
