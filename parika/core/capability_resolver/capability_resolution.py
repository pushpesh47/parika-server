"""
Immutable capability resolution result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from parika.core.capability_registry.capability_definition import CapabilityDefinition

from .capability_request import CapabilityRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityResolution:
    """
    Immutable result of capability resolution.

    A capability resolution represents a successfully resolved
    capability request. It combines the original request with the
    immutable capability definition retrieved from the registry.

    This object is passed to downstream core components for further
    evaluation and must never be modified after creation.
    """

    request: CapabilityRequest

    definition: CapabilityDefinition

    resolved_at: datetime