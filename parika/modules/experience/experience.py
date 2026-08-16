"""
PARIKA Experience

Defines the immutable Experience domain model recorded by the
Experience Module.

An Experience represents a single recorded execution outcome (or a
user correction of a prior one). It carries no reasoning: outcome
classification is decided by the caller (typically ExperienceRecorder,
translating an already-published TaskManager event), never inferred by
this object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from .experience_outcome import ExperienceOutcome


@dataclass(frozen=True, slots=True, kw_only=True)
class Experience:
    """Immutable record of one execution outcome."""

    experience_id: str
    capability_id: str
    outcome: ExperienceOutcome
    created_at: datetime

    provider_id: str | None = None
    model_id: str | None = None
    tool_id: str | None = None
    latency_ms: float | None = None
    token_count: int | None = None
    correction_of: str | None = None
    user_correction: str | None = None

    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if type(self.experience_id) is not str or not self.experience_id.strip():
            raise ValueError("experience_id must be a non-empty string.")

        if type(self.capability_id) is not str or not self.capability_id.strip():
            raise ValueError("capability_id must be a non-empty string.")

        if type(self.outcome) is not ExperienceOutcome:
            raise TypeError("outcome must be an ExperienceOutcome.")

        if type(self.created_at) is not datetime:
            raise TypeError("created_at must be a datetime.")

        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )
