"""
PARIKA Brain - Context Engine - Context Message

Defines a generic, provider-agnostic chat message representation for
`compact()`.

Brain (Core) must never depend on a Provider-specific message type
(e.g. `parika.providers.ollama.wire.OllamaMessage`) -- see Dependency
Rules, `PARIKA_Core_Coding_Standards.md`. Callers (typically the
Interfaces layer, which already depends on both Core and a specific
Provider's message shape) convert their own message type to
`ContextMessage` before calling `Brain.compact()`, and convert back
afterward. This conversion glue is deliberately kept out of Core.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextMessage:
    """One provider-agnostic message in a conversation history."""

    role: str
    content: str
    token_count: int | None = None

    def __post_init__(self) -> None:
        if type(self.role) is not str or not self.role.strip():
            raise ValueError("role must be a non-empty string.")

        if type(self.content) is not str:
            raise TypeError("content must be a string.")
