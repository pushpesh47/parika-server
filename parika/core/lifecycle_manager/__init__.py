"""
PARIKA Lifecycle Manager package.

Provides the LifecycleManager component and its primary public
interfaces.
"""

from .events import (
    LifecycleInitializedEvent,
    LifecycleReloadedEvent,
    LifecycleReloadFailedEvent,
    LifecycleStartedEvent,
    LifecycleStartFailedEvent,
    LifecycleStoppedEvent,
)
from .exceptions import (
    AlreadyInitializedError,
    HookAlreadyRegisteredError,
    InvalidLifecycleTransitionError,
    LifecycleHookError,
    LifecycleManagerError,
    NotInitializedError,
)
from .lifecycle_manager import LifecycleManager

__all__ = [
    "AlreadyInitializedError",
    "HookAlreadyRegisteredError",
    "InvalidLifecycleTransitionError",
    "LifecycleHookError",
    "LifecycleInitializedEvent",
    "LifecycleManager",
    "LifecycleManagerError",
    "LifecycleReloadedEvent",
    "LifecycleReloadFailedEvent",
    "LifecycleStartedEvent",
    "LifecycleStartFailedEvent",
    "LifecycleStoppedEvent",
    "NotInitializedError",
]
