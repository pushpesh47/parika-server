"""
PARIKA Update Record

Defines the mutable runtime UpdateRecord maintained by UpdateManager
for a single registered target.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .update_info import UpdateInfo
from .update_status import UpdateStatus


@dataclass(slots=True, kw_only=True)
class UpdateRecord:
    """
    Mutable runtime update record for a registered target.

    An UpdateRecord tracks the most recently observed update state of
    a single target. It is created, managed, and destroyed
    exclusively by UpdateManager and contains no business logic.
    """

    target_id: str
    """
    Identifier of the update target (e.g. "core",
    "module:web_search", "provider:ollama", "tool:web_search").
    """

    status: UpdateStatus = UpdateStatus.UNKNOWN
    """
    Current update state of the target.
    """

    current_version: str | None = None
    """
    Version currently installed for this target, if known.
    """

    pending_update: UpdateInfo | None = None
    """
    UpdateInfo describing the pending update, if the target's status
    is UPDATE_AVAILABLE.
    """

    last_checked_at: datetime | None = None
    """
    Timestamp of the most recent update check.
    """

    last_updated_at: datetime | None = None
    """
    Timestamp of the most recently applied update.
    """

    failure: BaseException | None = None
    """
    Exception raised by the most recent failed update attempt, if
    any.
    """

    metadata: MutableMapping[str, Any] = field(
        default_factory=dict,
    )
    """
    Mutable implementation-neutral runtime metadata.

    UpdateManager does not assign semantics to these values.
    """
