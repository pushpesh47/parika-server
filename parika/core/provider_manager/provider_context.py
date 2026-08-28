"""
PARIKA Core - ProviderManager Component - Provider Context

Abstracts provider-side conversation context/prefix reuse capability.
This is an optional optimization layer; providers that don't support
it simply return None from the context methods.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from parika.core.provider_manager.chat_message import ChatMessage
    from parika.core.provider_manager.provider_model import ProviderModel

T = TypeVar("T")
"""Provider-specific context handle type."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderContextIdentity:
    """
    Identity for a provider-side conversation context.
    
    Includes all dimensions that must match for a cached context
    to be reusable. Any change requires invalidation.
    """
    
    conversation_id: str
    """PARIKA conversation identifier."""
    
    provider_id: str
    """Provider identifier (e.g., 'provider.ollama')."""
    
    model_id: str
    """Model identifier within the provider."""
    
    static_prefix_version: int
    """Version of the static prefix (system/identity/policies)."""
    
    agent_context_id: str | None = None
    """Optional agent context for multi-agent isolation."""
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/debugging."""
        return {
            "conversation_id": self.conversation_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "static_prefix_version": self.static_prefix_version,
            "agent_context_id": self.agent_context_id,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderContextHandle(Generic[T]):
    """
    Opaque handle to a provider-side conversation context.
    
    The actual type T is provider-specific. PARIKA core never
    inspects the contents; it only passes this handle back to
    the provider when continuing the conversation.
    """
    
    identity: ProviderContextIdentity
    """Identity information for this context."""
    
    handle: T
    """Provider-specific context handle."""
    
    created_at: float
    """Timestamp when this context was created (for TTL/eviction)."""


class ProviderContextCapability(ABC, Generic[T]):
    """
    Abstract interface for provider-side conversation context reuse.
    
    Providers that support KV-cache/prefix reuse implement this
    interface. Providers that don't support it return None from
    all methods (the default implementation).
    """
    
    @property
    def supports_context_reuse(self) -> bool:
        """Whether this provider supports context reuse."""
        return False
    
    def create_context(
        self,
        model: "ProviderModel",
        static_prefix: tuple["ChatMessage", ...],
        conversation_history: tuple["ChatMessage", ...],
        identity: ProviderContextIdentity,
    ) -> "ProviderContextHandle[T] | None":
        """
        Create a new provider-side context from the initial conversation.
        
        Called when a conversation starts or when an existing
        conversation needs to establish a new provider context
        (e.g., after cache invalidation).
        
        Args:
            model: The selected model.
            static_prefix: System/identity/policy messages.
            conversation_history: Existing user/assistant history.
            identity: Identity for this context.
        
        Returns:
            ProviderContextHandle if successful, None if the
            provider cannot create a context (falls back to normal
            full-context requests).
        """
        return None
    
    def continue_context(
        self,
        model: "ProviderModel",
        context_handle: "ProviderContextHandle[T]",
        new_messages: tuple["ChatMessage", ...],
    ) -> "ProviderContextHandle[T] | None":
        """
        Continue an existing provider-side context with new messages.
        
        Called on subsequent turns when a valid context exists.
        
        Args:
            model: The selected model.
            context_handle: Existing provider context handle.
            new_messages: New messages since last turn (user +
                injected context + assistant response).
        
        Returns:
            Updated ProviderContextHandle if successful, None if
            the provider cannot continue (falls back to normal
            full-context requests).
        """
        return None
    
    def invalidate_context(
        self,
        context_handle: "ProviderContextHandle[T]",
    ) -> None:
        """
        Explicitly invalidate a provider-side context.
        
        Called when conversation context changes in a way that
        makes the cached context invalid (agent switch, model
        switch, static prefix change, etc.).
        """
        pass


def create_provider_context_capability(
    provider_id: str,
    model: "ProviderModel",
) -> "ProviderContextCapability[Any] | None":
    """
    Factory to create a provider context capability instance.
    
    Returns None for providers that don't support context reuse.
    This is the integration point for provider-specific
    implementations.
    """
    return None


# Ollama-specific implementation (currently no-op since Ollama
# doesn't expose conversation context reuse in /api/chat)
class OllamaContextCapability(ProviderContextCapability[None]):
    """Ollama provider context capability (no-op implementation)."""
    
    @property
    def supports_context_reuse(self) -> bool:
        return False
    
    def create_context(
        self,
        model: "ProviderModel",
        static_prefix: tuple["ChatMessage", ...],
        conversation_history: tuple["ChatMessage", ...],
        identity: ProviderContextIdentity,
    ) -> "ProviderContextHandle[None] | None":
        return None
    
    def continue_context(
        self,
        model: "ProviderModel",
        context_handle: "ProviderContextHandle[None]",
        new_messages: tuple["ChatMessage", ...],
    ) -> "ProviderContextHandle[None] | None":
        return None