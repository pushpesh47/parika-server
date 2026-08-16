"""
PARIKA Experience Module - Driver

Implements the ModuleDriver contract for the Experience Module.

`ExperienceStore` itself is constructed and initialized directly by
the composition root (`runtime.py`), *before* `Planner` is constructed
-- exactly like `MemoryManager`/`SqliteKnowledgeStorage` -- because
Planner needs a ready `experience_source` at construction time, and
Module loading happens later in `build_default_runtime()`. This
driver's job is therefore narrower than most Module drivers: on
start(), it only subscribes the ExperienceRecorder to TaskManager's
already-published events; on stop(), it only unsubscribes. It never
registers a Capability or Tool -- Experience has no user-facing
capability of its own.
"""

from __future__ import annotations

from parika.core.event_bus.event_bus import EventBus
from parika.core.health_manager.health_check_result import HealthCheckResult
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.module_manager.driver import ModuleDriver

from .experience_store import ExperienceStore
from .recorder import ExperienceRecorder

MODULE_HEALTH_COMPONENT_ID = "module.experience"


class ExperienceModuleDriver(ModuleDriver):
    """Runtime driver for the Experience Module."""

    def __init__(
        self,
        *,
        experience_store: ExperienceStore,
        event_bus: EventBus,
        health_manager: HealthManager | None = None,
    ) -> None:
        self._experience_store = experience_store
        self._recorder = ExperienceRecorder(event_bus, experience_store)
        self._health_manager = health_manager

    def start(self) -> None:
        self._recorder.initialize()

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

    def stop(self) -> None:
        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._recorder.shutdown()

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)
