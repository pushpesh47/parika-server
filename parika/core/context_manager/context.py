"""
PARIKA Runtime Context

Defines the immutable Context domain model managed by the ContextManager.

A Context represents a single transient runtime context. It is an immutable
value object containing only contextual information and carries no business
logic or execution behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from .context_status import ContextStatus
from .context_type import ContextType


@dataclass(frozen=True, slots=True, kw_only=True)
class Context:
    """
    Immutable runtime context.

    A Context represents a single transient runtime context managed by the
    ContextManager.

    Attributes:
        context_id:
            Globally unique context identifier.

        context_type:
            Classification of the context.

        status:
            Current lifecycle status.

        created_at:
            UTC timestamp when the context was created.

        updated_at:
            UTC timestamp when the context was last updated.

        metadata:
            Immutable contextual metadata.
    """

    context_id: str
    context_type: ContextType
    status: ContextStatus
    created_at: datetime
    updated_at: datetime

    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """
        Validate the Context after initialization.
        """

        if type(self.context_id) is not str:
            raise TypeError("context_id must be a string.")

        if not self.context_id.strip():
            raise ValueError("Context ID cannot be empty.")

        if type(self.context_type) is not ContextType:
            raise TypeError("context_type must be a ContextType.")

        if type(self.status) is not ContextStatus:
            raise TypeError("status must be a ContextStatus.")

        if type(self.created_at) is not datetime:
            raise TypeError("created_at must be a datetime.")

        if type(self.updated_at) is not datetime:
            raise TypeError("updated_at must be a datetime.")

        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be earlier than created_at.")

        if type(self.metadata) is not MappingProxyType:
            raise TypeError("metadata must be a MappingProxyType.")

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )