"""
PARIKA Experience Store

Public entry point for the Experience Module. Validates inputs,
coordinates persistence through ExperienceStorage, and satisfies
Planner's `ExperienceSource` Protocol structurally (via
`aggregate_outcome_rate()`) -- without Planner ever importing this
class. See docs/architecture/Intelligence_Foundation_Design.md section
6A for the full rationale.

Thread Safety
-------------
ExperienceStore is thread-safe. All public operations are protected by
an internal re-entrant lock, mirroring MemoryManager's pattern.
"""

from __future__ import annotations

from pathlib import Path, PurePath
from threading import RLock

from parika.core.logger.logger import Logger

from .exceptions import ExperienceNotFoundError, InvalidExperienceError
from .experience import Experience
from .postgresql_storage import PostgreSQLExperienceStorage


class ExperienceStore:
    """
    Thread-safe coordinator for recording and querying Experience
    data.
    """

    __slots__ = ("_logger", "_storage", "_lock")

    def __init__(
        self, 
        logger: Logger, 
        storage: PostgreSQLExperienceStorage,
    ) -> None:
        if type(logger) is not Logger:
            raise TypeError("logger must be of type Logger.")

        self._logger = logger.get_logger(__name__)
        self._storage = storage
        self._lock = RLock()

    def initialize(self) -> None:
        with self._lock:
            self._logger.info("Initializing ExperienceStore.")
            self._storage.initialize()
            self._logger.info("ExperienceStore initialized successfully.")

    def shutdown(self) -> None:
        with self._lock:
            self._logger.info("Shutting down ExperienceStore.")
            self._storage.shutdown()
            self._logger.info("ExperienceStore shutdown completed.")

    def register(self, experience: Experience) -> Experience:
        if type(experience) is not Experience:
            raise InvalidExperienceError("experience must be of type Experience.")

        with self._lock:
            registered = self._storage.insert(experience)
            self._logger.debug(
                "Registered experience '%s' for capability '%s' (%s).",
                registered.experience_id,
                registered.capability_id,
                registered.outcome.value,
            )
            return registered

    def get(self, experience_id: str) -> Experience:
        with self._lock:
            experience = self._storage.get(experience_id)

            if experience is None:
                raise ExperienceNotFoundError(
                    f"Experience '{experience_id}' was not found."
                )

            return experience

    def get_all(self) -> tuple[Experience, ...]:
        with self._lock:
            return self._storage.get_all()

    def get_by_capability(self, capability_id: str) -> tuple[Experience, ...]:
        with self._lock:
            return self._storage.get_by_capability(capability_id)

    def aggregate_outcome_rate(
        self,
        *,
        capability_id: str,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> float | None:
        """
        Return the historical success rate in [0, 1] for the given
        filters, or `None` when no matching data exists yet. Satisfies
        Planner's `ExperienceSource` Protocol structurally.
        """

        with self._lock:
            successes, total = self._storage.aggregate_outcome_rate(
                capability_id=capability_id,
                provider_id=provider_id,
                model_id=model_id,
            )

            if total == 0:
                return None

            return successes / total
