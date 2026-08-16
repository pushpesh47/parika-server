"""
PARIKA Task Response

Defines the immutable execution response returned by TaskManager after
successful Task execution.

A TaskResponse encapsulates the outputs produced by an executed
Capability together with implementation-neutral execution metadata and
the reported execution duration.

TaskResponse is an immutable value object and carries no execution
state or business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class TaskResponse:
    """
    Immutable execution response for a Task.

    A TaskResponse represents the successful output produced by an
    executed Capability. It serves as the immutable execution result
    stored by TaskManager after successful Task completion.
    """

    outputs: Mapping[str, Any] = field(default_factory=dict)
    """
    Immutable outputs produced by the executed Capability.
    """

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """
    Implementation-neutral metadata associated with the execution
    result.

    TaskManager does not interpret or modify these values.
    """

    duration_seconds: float | None = None
    """
    Backend-reported execution duration in seconds.

    This value represents the time spent executing the Capability and
    is independent of Task lifecycle timestamps maintained by
    TaskManager.
    """

    def __post_init__(self) -> None:
        """
        Convert mutable mappings into immutable mapping proxies.

        Defensive copies are created to ensure TaskResponse remains
        deeply immutable even if mutable dictionaries are supplied by
        callers.
        """

        object.__setattr__(
            self,
            "outputs",
            MappingProxyType(dict(self.outputs)),
        )

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )