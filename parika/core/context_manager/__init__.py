"""
Context management subsystem.

This package provides immutable Context models, supporting
enumerations, events, exceptions, and the ContextManager
responsible for registering and managing Context instances.
"""

from .context import Context
from .context_manager import ContextManager
from .context_status import ContextStatus
from .context_type import ContextType
from .events import (
    ContextRegistered,
    ContextRemoved,
    ContextUpdated,
)
from .exceptions import (
    ContextAlreadyExistsError,
    ContextManagerError,
    ContextNotFoundError,
    InvalidContextError,
)

__all__ = [
    "Context",
    "ContextManager",
    "ContextStatus",
    "ContextType",
    "ContextRegistered",
    "ContextUpdated",
    "ContextRemoved",
    "ContextManagerError",
    "ContextAlreadyExistsError",
    "ContextNotFoundError",
    "InvalidContextError",
]