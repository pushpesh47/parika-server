"""
PARIKA Update Manager package.

Provides the UpdateManager component and its primary public
interfaces.
"""

from .events import (
    MigrationAppliedEvent,
    TargetRegisteredEvent,
    TargetUnregisteredEvent,
    UpdateAppliedEvent,
    UpdateAvailableEvent,
    UpdateFailedEvent,
    UpdateUpToDateEvent,
)
from .exceptions import (
    InvalidUpdateTargetError,
    MigrationAlreadyRegisteredError,
    MigrationError,
    TargetAlreadyRegisteredError,
    TargetNotFoundError,
    UpdateApplyError,
    UpdateManagerError,
    UpdateNotAvailableError,
)
from .update_info import UpdateInfo
from .update_manager import UpdateManager
from .update_record import UpdateRecord
from .update_status import UpdateStatus

__all__ = [
    "InvalidUpdateTargetError",
    "MigrationAlreadyRegisteredError",
    "MigrationAppliedEvent",
    "MigrationError",
    "TargetAlreadyRegisteredError",
    "TargetNotFoundError",
    "TargetRegisteredEvent",
    "TargetUnregisteredEvent",
    "UpdateAppliedEvent",
    "UpdateApplyError",
    "UpdateAvailableEvent",
    "UpdateFailedEvent",
    "UpdateInfo",
    "UpdateManager",
    "UpdateManagerError",
    "UpdateNotAvailableError",
    "UpdateRecord",
    "UpdateStatus",
    "UpdateUpToDateEvent",
]
