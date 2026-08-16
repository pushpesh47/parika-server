"""
PARIKA Brain Request

Defines the immutable BrainRequest submitted to Brain.

A BrainRequest carries the already-decomposed Goal instances that
Brain should turn into an ExecutionPlan and supervise to completion.
Semantic decomposition of free-form user input into Goals is
performed by the caller (e.g. an Interface or a future AI-reasoning
Module); Brain only coordinates already-structured Goals.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from parika.core.planner.goal import Goal


@dataclass(
    frozen=True,
    slots=True,
    kw_only=True,
)
class BrainRequest:
    """
    Immutable request submitted to Brain.

    A BrainRequest carries one or more already-decomposed Goal
    instances for Brain to plan and supervise to completion.
    """

    goals: tuple[Goal, ...]
    """
    Goals to plan and execute.
    """

    id: str = field(default_factory=lambda: uuid4().hex)
    """
    Unique identifier of this request.
    """

    metadata: Mapping[str, Any] = field(default_factory=dict)
    """
    Implementation-neutral metadata associated with this request.
    """

    def __post_init__(self) -> None:
        """
        Normalize mutable inputs into immutable equivalents.
        """

        object.__setattr__(self, "goals", tuple(self.goals))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )
