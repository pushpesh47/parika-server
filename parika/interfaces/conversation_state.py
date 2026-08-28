"""
PARIKA Interfaces - Conversation State

Defines the explicit, authoritative conversation state representation
that separates static prefix (system/identity/policies) from dynamic
conversation history and per-turn injected context.

This is the single source of truth for conversation state. Provider-side
caching is an optional optimization layered on top of this state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from parika.core.provider_manager.chat_message import ChatMessage
from parika.interfaces.history import HistoryEntry, HistoryRole
from parika.interfaces.postgresql_session_store import PostgreSQLSessionStore


@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationStaticPrefix:
    """
    Immutable static prefix for a conversation.
    
    Contains system/identity/behavior/policy messages that are stable
    for the conversation's execution context. Versioned for cache
    invalidation when provider-side prefix caching is available.
    """
    
    messages: tuple[ChatMessage, ...]
    """System messages: identity, behavior, constraints, policies."""
    
    version: int = 1
    """Version for cache invalidation. Incremented when static content changes."""
    
    agent_context_id: str | None = None
    """Optional agent context identifier for multi-agent isolation."""
    
    def with_updated_messages(self, messages: tuple[ChatMessage, ...]) -> "ConversationStaticPrefix":
        """Return new prefix with updated messages and incremented version."""
        return ConversationStaticPrefix(
            messages=messages,
            version=self.version + 1,
            agent_context_id=self.agent_context_id,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationState:
    """
    Authoritative conversation state representation.
    
    Separates static prefix (system/identity/policies) from dynamic
    conversation history and injected context. This state is the
    single source of truth for conversation continuity.
    
    Provider-side context reuse is an optional optimization built on
    top of this state, never the source of truth.
    """
    
    id: str
    """Unique conversation identifier."""
    
    static_prefix: ConversationStaticPrefix
    """Static system/identity/behavior/policy messages."""
    
    conversation_history: tuple[ChatMessage, ...] = field(default_factory=tuple)
    """Rolling user/assistant message history."""
    
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    """Conversation start timestamp."""
    
    def __init__(
        self,
        *,
        id: str | None = None,
        static_prefix: ConversationStaticPrefix,
        conversation_history: tuple[ChatMessage, ...] = (),
        started_at: datetime | None = None,
    ) -> None:
        object.__setattr__(self, "id", id or uuid4().hex)
        object.__setattr__(self, "static_prefix", static_prefix)
        object.__setattr__(self, "conversation_history", conversation_history)
        object.__setattr__(self, "started_at", started_at or datetime.now(UTC))
    
    @property
    def full_history(self) -> tuple[ChatMessage, ...]:
        """Complete conversation including static prefix and history."""
        return self.static_prefix.messages + self.conversation_history
    
    def append_user_message(self, message: ChatMessage) -> "ConversationState":
        """Return new state with user message appended."""
        return ConversationState(
            id=self.id,
            static_prefix=self.static_prefix,
            conversation_history=self.conversation_history + (message,),
            started_at=self.started_at,
        )
    
    def append_assistant_message(self, message: ChatMessage) -> "ConversationState":
        """Return new state with assistant message appended."""
        return ConversationState(
            id=self.id,
            static_prefix=self.static_prefix,
            conversation_history=self.conversation_history + (message,),
            started_at=self.started_at,
        )
    
    def with_updated_static_prefix(self, static_prefix: ConversationStaticPrefix) -> "ConversationState":
        """Return new state with updated static prefix (for agent/context changes)."""
        return ConversationState(
            id=self.id,
            static_prefix=static_prefix,
            conversation_history=self.conversation_history,
            started_at=self.started_at,
        )
    
    def clear_history(self) -> "ConversationState":
        """Return new state with history cleared but static prefix preserved."""
        return ConversationState(
            id=self.id,
            static_prefix=self.static_prefix,
            conversation_history=(),
            started_at=self.started_at,
        )


def build_static_prefix(
    runtime: "ParikaRuntime",
    *,
    system_prompt: str | None = None,
    agent_context_id: str | None = None,
) -> ConversationStaticPrefix:
    """
    Build the static prefix for a conversation.
    
    Args:
        runtime: Runtime providing configuration and identity.
        system_prompt: Optional explicit system prompt. If None, builds
            default Assistant Identity from configuration.
        agent_context_id: Optional agent context for multi-agent isolation.
    
    Returns:
        ConversationStaticPrefix with system/identity/behavior/policy messages.
    """
    from .ai_context.prompt_builder import build_assistant_system_prompt
    
    resolved_system_prompt = (
        build_assistant_system_prompt(runtime.configuration)
        if system_prompt is None
        else system_prompt
    )
    
    messages = ()
    if resolved_system_prompt:
        messages = (ChatMessage(role="system", content=resolved_system_prompt),)
    
    return ConversationStaticPrefix(
        messages=messages,
        version=1,
        agent_context_id=agent_context_id,
    )


class ConversationStateManager:
    """
    Manages ConversationState persistence and reconstruction.
    
    This is the single authority for loading/saving conversation state
    from PostgreSQL. Provider-side caching is never authoritative.
    """
    
    def __init__(
        self,
        session_store: PostgreSQLSessionStore | None = None,
    ) -> None:
        self._session_store = session_store
    
    def create_initial_state(
        self,
        runtime: "ParikaRuntime",
        *,
        session_id: str | None = None,
        system_prompt: str | None = None,
        agent_context_id: str | None = None,
    ) -> ConversationState:
        """Create a new conversation state with initial static prefix."""
        cid = session_id or uuid4().hex
        
        static_prefix = build_static_prefix(
            runtime,
            system_prompt=system_prompt,
            agent_context_id=agent_context_id,
        )
        
        state = ConversationState(
            id=cid,
            static_prefix=static_prefix,
        )
        
        if self._session_store is not None:
            self._session_store.ensure_session(cid)
        
        return state
    
    def save_state(self, state: ConversationState) -> None:
        """Persist conversation state to PostgreSQL."""
        if self._session_store is None:
            return
        
        # Ensure session exists
        self._session_store.ensure_session(state.id)
        
        # Save all messages except system (system is in static_prefix)
        for message in state.conversation_history:
            self._session_store.append_message(
                state.id,
                role=message.role,
                content=message.content,
            )
        
        # Note: static_prefix is not persisted separately; it's derived
        # from configuration at load time. The version handles cache invalidation.
    
    def load_state(
        self,
        session_id: str,
        runtime: "ParikaRuntime",
        *,
        system_prompt: str | None = None,
        agent_context_id: str | None = None,
    ) -> ConversationState:
        """
        Reconstruct conversation state from PostgreSQL.
        
        Raises SessionNotFoundError if session doesn't exist.
        """
        if self._session_store is None:
            raise RuntimeError("No session store configured for state loading")
        
        if self._session_store.get_session(session_id) is None:
            from .postgresql_session_store import SessionNotFoundError
            raise SessionNotFoundError(f"Session '{session_id}' was not found.")
        
        static_prefix = build_static_prefix(
            runtime,
            system_prompt=system_prompt,
            agent_context_id=agent_context_id,
        )
        
        state = ConversationState(
            id=session_id,
            static_prefix=static_prefix,
            started_at=datetime.now(UTC),  # Will be updated from first message if available
        )
        
        for message in self._session_store.get_messages(session_id):
            if message.role == "system":
                continue  # System is in static_prefix
            
            if message.role in ("user", "assistant"):
                chat_message = ChatMessage(
                    role=message.role,
                    content=message.content,
                )
                state = state.append_user_message(chat_message) if message.role == "user" \
                    else state.append_assistant_message(chat_message)
        
        return state
    
    def list_states(self) -> tuple["SessionSummary", ...]:
        """List all available conversation states."""
        if self._session_store is None:
            return ()
        return self._session_store.list_sessions()


# Import at bottom to avoid circular imports
from parika.interfaces.runtime import ParikaRuntime
from parika.interfaces.postgresql_session_store import SessionSummary