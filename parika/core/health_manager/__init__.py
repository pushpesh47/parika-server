"""
PARIKA Health Manager package.

Provides the HealthManager component and its primary public
interfaces.
"""

from .component_health import ComponentHealth
from .events import (
    ComponentHealthChangedEvent,
    ComponentRecoveryFailedEvent,
    ComponentRecoveryTriggeredEvent,
    ComponentRegisteredEvent,
    ComponentUnregisteredEvent,
)
from .exceptions import (
    ComponentAlreadyRegisteredError,
    ComponentNotFoundError,
    HealthManagerError,
    InvalidHealthCheckError,
)
from .health_check_result import HealthCheckResult
from .health_manager import HealthManager
from .health_status import HealthStatus

__all__ = [
    "ComponentAlreadyRegisteredError",
    "ComponentHealth",
    "ComponentHealthChangedEvent",
    "ComponentNotFoundError",
    "ComponentRecoveryFailedEvent",
    "ComponentRecoveryTriggeredEvent",
    "ComponentRegisteredEvent",
    "ComponentUnregisteredEvent",
    "HealthCheckResult",
    "HealthManager",
    "HealthManagerError",
    "HealthStatus",
    "InvalidHealthCheckError",
]
