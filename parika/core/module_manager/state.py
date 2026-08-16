"""
PARIKA Module State

Defines the operational states of registered Modules managed by the
ModuleManager.

The module state describes the operational availability of a Module.
It is descriptive only and does not define or enforce lifecycle
transitions such as loading, initialization, or unloading.

Lifecycle orchestration is managed internally by ModuleManager.
"""

from __future__ import annotations

from enum import StrEnum


class ModuleState(StrEnum):
    """
    Operational state of a registered Module.

    The module state represents the current operational availability of
    a Module. It is descriptive only and carries no business logic.
    """

    ACTIVE = "active"
    """The module is operational and available for use."""

    INACTIVE = "inactive"
    """The module is registered but not currently operational."""

    FAILED = "failed"
    """The module encountered an unrecoverable runtime failure."""

    DISABLED = "disabled"
    """The module has been intentionally disabled."""