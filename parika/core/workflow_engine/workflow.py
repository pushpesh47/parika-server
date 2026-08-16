"""
PARIKA Workflow

Defines the immutable Workflow model managed by WorkflowEngine.

A Workflow represents a reusable workflow definition consisting of an
ordered collection of immutable Step definitions and an entry step.

A Workflow contains no runtime execution state or business logic.
Runtime execution is represented by Execution and managed internally
by WorkflowEngine.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .workflow_step import Step


@dataclass(frozen=True, slots=True, kw_only=True)
class Workflow:
    """
    Immutable workflow definition.

    A Workflow defines a reusable collection of immutable Step
    definitions together with the entry point used to begin execution.
    A Workflow contains no runtime execution state and carries no
    business logic.
    """

    id: str
    """Unique identifier of the Workflow."""

    name: str
    """Human-readable name of the Workflow."""

    description: str | None = None
    """Optional description of the Workflow."""

    version: str
    """Version of the Workflow definition."""

    step_definitions: Mapping[str, Step] = field(default_factory=dict)
    """Immutable mapping of Step identifiers to Step definitions."""

    entry_step_id: str
    """Identifier of the first Step executed by the Workflow."""

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """Optional implementation-neutral metadata associated with the Workflow."""