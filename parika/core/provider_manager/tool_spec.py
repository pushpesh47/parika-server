"""
PARIKA Core - ProviderManager Component

Defines the provider-independent tool specification representation.

`ToolSpec` describes one Capability advertised to a chat-capable model
as a callable tool/function: a name, a human-readable description,
and a JSON Schema for its parameters. This is the semantic tool
schema shared by essentially every tool-calling provider (Ollama,
OpenAI, Gemini, Claude); translating it into a concrete wire payload
(e.g. Ollama's `{"type": "function", "function": {...}}` nesting) is
the responsibility of the specific `ProviderDriver` that receives it,
never a provider-independent layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolSpec:
    """
    Immutable, provider-independent tool specification.

    Attributes:
        name:
            Function name advertised to the model.

        description:
            Human-readable description shown to the model.

        parameters:
            JSON Schema describing the function's parameters.

        capability_id:
            PARIKA capability identifier this tool spec maps to. When
            the model calls `name`, the provider driver resolves this
            capability id and invokes it through Brain.
    """

    name: str
    description: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    capability_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )
