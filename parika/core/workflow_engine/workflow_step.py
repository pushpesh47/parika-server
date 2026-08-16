"""
PARIKA Workflow Step

Defines the immutable Step model used by WorkflowEngine.

A Step represents a single executable unit within a Workflow definition.
It specifies the Capability to execute, the input and output mappings,
and the identifiers of subsequent workflow steps.

A Step is immutable and contains no runtime execution state or business
logic. Runtime execution is represented by Execution and managed
internally by WorkflowEngine.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class Step:
    """
    Immutable definition of a workflow step.

    A Step defines a single executable unit within a Workflow. It
    describes the Capability to invoke, the input and output mappings,
    and the identifiers of subsequent workflow steps. A Step contains
    no execution state and carries no business logic.
    """

    id: str
    """Unique identifier of the Step within its Workflow."""

    name: str
    """Human-readable name of the Step."""

    description: str | None = None
    """Optional description of the Step."""

    capability_id: str
    """Identifier of the Capability executed by this Step."""

    inputs: Mapping[str, Any] = field(default_factory=dict)
    """Static input mappings supplied to the Capability."""

    outputs: Mapping[str, str] = field(default_factory=dict)
    """Mappings of Capability outputs into the execution Context."""

    next_step_ids: tuple[str, ...] = ()
    """Identifiers of the subsequent Steps."""

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """Optional implementation-neutral metadata associated with the Step."""