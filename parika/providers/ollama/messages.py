"""
PARIKA Ollama Provider - Messages and Tool Specifications

Defines the immutable domain objects exchanged with the Ollama chat
API: chat messages, tool calls requested by a model, and tool
specifications advertised to a model.

These types are Ollama-specific and intentionally live alongside the
Ollama provider driver rather than in `parika.core.provider_manager`,
matching the architecture's expectation that concrete `ProviderRequest`
/ `ProviderResponse` payloads are provider-specific (see
`PARIKA_Decision_Flow.md` section 4.4 and `Running.md` section 6).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaToolCall:
    """
    Immutable tool call requested by an Ollama model.
    """

    name: str
    """
    Name of the function the model wants to call, as sent by Ollama.
    """

    arguments: Mapping[str, Any] = field(default_factory=dict)
    """
    Arguments the model supplied for the call.
    """

    id: str | None = None
    """
    Optional call identifier, when reported by the model/server.
    """

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "arguments",
            MappingProxyType(dict(self.arguments)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaMessage:
    """
    Immutable chat message exchanged with the Ollama chat API.
    """

    role: str
    """
    Message role: "system", "user", "assistant", or "tool".
    """

    content: str = ""
    """
    Text content of the message.
    """

    tool_calls: tuple[OllamaToolCall, ...] = ()
    """
    Tool calls requested by the model. Only populated on "assistant"
    messages produced by Ollama.
    """

    tool_call_id: str | None = None
    """
    Identifier of the tool call this message answers. Only used on
    "tool" role messages.
    """

    name: str | None = None
    """
    Name of the tool that produced this message. Only used on "tool"
    role messages.
    """

    images: tuple[str, ...] = ()
    """
    Base64-encoded image bytes to attach to this message, in Ollama's
    own `images` wire field (`POST /api/chat`'s per-message `images`
    array). This is Ollama-specific, provider-owned image-input
    serialization -- the caller supplying it (typically a Module's own
    `Goal.provider_request_builder`, exactly like `messages`/`content`
    already are) already has the raw base64 string from an existing,
    unmodified Capability (e.g. `filesystem.read` with `binary=true`,
    see `parika.tools.filesystem.operations.read()`); this field never
    encodes anything itself, it only carries an already-encoded string
    through to `to_payload()`. Empty by default, so every existing
    `OllamaMessage(...)` construction is unaffected.
    """

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tool_calls",
            tuple(self.tool_calls),
        )
        object.__setattr__(
            self,
            "images",
            tuple(self.images),
        )

    def to_payload(self) -> dict[str, Any]:
        """
        Convert this message into the JSON payload shape expected by
        the Ollama chat API.
        """

        payload: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }

        if self.images:
            payload["images"] = list(self.images)

        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "function": {
                        "name": call.name,
                        "arguments": dict(call.arguments),
                    },
                }
                for call in self.tool_calls
            ]

        if self.role == "tool" and self.name is not None:
            payload["name"] = self.name

        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaToolSpec:
    """
    Immutable specification of a capability advertised to an Ollama
    model as a callable tool/function.
    """

    name: str
    """
    Function name advertised to the model. Ollama function names may
    not contain '.', so this is typically a capability id with '.'
    replaced by '_'.
    """

    description: str
    """
    Human-readable description shown to the model.
    """

    parameters: Mapping[str, Any] = field(default_factory=dict)
    """
    JSON Schema describing the function's parameters.
    """

    capability_id: str = ""
    """
    PARIKA capability identifier this tool spec maps to. When the
    model calls `name`, the Ollama provider driver resolves this
    capability id and invokes it through Brain.
    """

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )

    def to_payload(self) -> dict[str, Any]:
        """
        Convert this tool spec into the JSON payload shape expected
        by the Ollama chat API's `tools` field.
        """

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }
