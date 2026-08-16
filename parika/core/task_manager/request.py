"""
PARIKA Task Request

Defines the immutable execution request submitted to TaskManager for
runtime Task execution.

A TaskRequest encapsulates the information required to execute a
Capability. It represents the execution contract between TaskManager
and CapabilityResolver and contains the capability identifier,
execution inputs, optional execution context, and implementation-
neutral metadata.

TaskRequest is an immutable value object and carries no execution
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
class TaskRequest:
    """
    Immutable execution request for a Task.

    A TaskRequest contains the information required by TaskManager to
    execute a Capability. It serves as the execution contract passed
    to CapabilityResolver and remains immutable throughout the Task
    lifecycle.
    """

    capability_id: str
    """
    Identifier of the Capability to execute.
    """

    inputs: Mapping[str, Any] = field(default_factory=dict)
    """
    Immutable input parameters supplied to the Capability.
    """

    context_id: str | None = None
    """
    Optional identifier of the execution Context associated with the
    Task.
    """

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """
    Implementation-neutral metadata associated with the execution
    request.

    TaskManager does not interpret or modify these values.
    """

    def __post_init__(self) -> None:
        """
        Convert mutable mappings into immutable mapping proxies.

        Defensive copies are created to ensure TaskRequest remains
        deeply immutable even if mutable dictionaries are supplied by
        callers.
        """

        object.__setattr__(
            self,
            "inputs",
            MappingProxyType(dict(self.inputs)),
        )

        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )