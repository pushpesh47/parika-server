"""
PARIKA Event Matcher

Provides flexible event matching for wait conditions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Callable

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


@dataclass(frozen=True, slots=True, kw_only=True)
class EventPattern:
    """Pattern for matching events."""
    event_type: str | None = None
    source: str | None = None
    required_fields: MappingProxyType[str, Any] = MappingProxyType({})
    custom_matcher: Callable[[MappingProxyType[str, Any]], bool] | None = None

    def matches(self, event: MappingProxyType[str, Any]) -> bool:
        """Check if event matches pattern."""
        if self.event_type and event.get("event_type") != self.event_type:
            return False

        if self.source and event.get("source") != self.source:
            return False

        for key, value in self.required_fields.items():
            if event.get(key) != value:
                return False

        if self.custom_matcher and not self.custom_matcher(event):
            return False

        return True


class EventMatcher:
    """
    Matches events against patterns for wait condition satisfaction.

    Supports:
    - Exact field matching
    - Pattern matching
    - Custom matcher functions
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._patterns: dict[str, EventPattern] = {}

    def register_pattern(self, pattern_id: str, pattern: EventPattern) -> None:
        """Register an event pattern."""
        self._patterns[pattern_id] = pattern

    def unregister_pattern(self, pattern_id: str) -> None:
        """Unregister an event pattern."""
        self._patterns.pop(pattern_id, None)

    def match(self, event: MappingProxyType[str, Any]) -> list[str]:
        """
        Match event against all registered patterns.

        Returns list of matching pattern IDs.
        """
        matches = []
        for pattern_id, pattern in self._patterns.items():
            if pattern.matches(event):
                matches.append(pattern_id)
        return matches

    def create_wait_pattern(
        self,
        wait_condition_type: str,
        **field_filters,
    ) -> EventPattern:
        """
        Create a pattern for a wait condition type.

        Args:
            wait_condition_type: Type of wait condition
            **field_filters: Field filters to match

        Returns:
            EventPattern for the wait condition
        """
        return EventPattern(
            required_fields=field_filters,
        )