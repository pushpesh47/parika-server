"""
PARIKA Core - ProviderManager Component

Defines the provider-independent chat message representation.

`ChatMessage` represents one turn of a conversation -- "system",
"user", or "assistant" role -- in a form no provider-specific wire
format leaks into. Every provider-independent layer (Interfaces, AI
Context Engineering, Modules) builds and reads only this type; a
selected `ProviderDriver` translates it into its own concrete wire
representation (e.g. Ollama's `OllamaMessage`) at the provider
boundary, and translates its own concrete response back into this
type (see `chat_result.ChatResult`).

Deliberately excludes any tool-calling wire concept ("tool" role,
tool call ids, tool call payloads): resolving a model's tool call into
a PARIKA capability invocation, and feeding the outcome back to the
model, is entirely an internal chat-loop responsibility of whichever
ProviderDriver implements it (see `parika.providers.ollama.chat_loop`)
-- no provider-independent layer ever constructs or inspects a "tool"
role message.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ChatMessage:
    """
    Immutable, provider-independent chat message.

    Attributes:
        role:
            Message role: "system", "user", or "assistant".

        content:
            Text content of the message.

        images:
            Base64-encoded image bytes attached to this message, for
            multimodal Provider capabilities (Vision, Video, OCR).
            Empty for an ordinary text-only message.

            This carries an already-encoded string through to
            whichever ProviderDriver ultimately receives it; it never
            encodes anything itself. Translating it into a concrete
            provider-specific wire field (e.g. Ollama's `images`
            array) is the responsibility of that ProviderDriver;
            providers with no multimodal support simply ignore it.
    """

    role: str
    content: str = ""
    images: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "images", tuple(self.images))
