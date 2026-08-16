"""
Unit tests for ExperienceStore, ExperienceRecorder, and
ExperienceModuleDriver.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.task_manager.events import TaskCompletedEvent, TaskFailedEvent
from parika.core.task_manager.request import TaskRequest
from parika.core.task_manager.response import TaskResponse
from parika.core.task_manager.task import Task
from parika.core.task_manager.task_manager import (
    TASK_COMPLETED_EVENT,
    TASK_FAILED_EVENT,
)
from parika.core.task_manager.task_status import TaskStatus
from parika.modules.experience.driver import ExperienceModuleDriver
from parika.modules.experience.exceptions import (
    ExperienceNotFoundError,
    InvalidExperienceError,
)
from parika.modules.experience.experience import Experience
from parika.modules.experience.experience_outcome import ExperienceOutcome
from parika.modules.experience.experience_store import ExperienceStore
from parika.modules.experience.recorder import ExperienceRecorder


def _make_experience(
    *,
    experience_id: str = "exp-1",
    capability_id: str = "web.search",
    outcome: ExperienceOutcome = ExperienceOutcome.SUCCESS,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> Experience:
    return Experience(
        experience_id=experience_id,
        capability_id=capability_id,
        outcome=outcome,
        created_at=datetime.now(UTC),
        provider_id=provider_id,
        model_id=model_id,
    )


@pytest.fixture
def store(logger: Logger, tmp_path: Path) -> Iterator[ExperienceStore]:
    store = ExperienceStore(logger=logger, database_path=tmp_path / "experience.db")
    store.initialize()

    yield store

    store.shutdown()


class TestExperienceStore:
    def test_register_and_get(self, store: ExperienceStore) -> None:
        registered = store.register(_make_experience())

        fetched = store.get("exp-1")

        assert fetched == registered

    def test_get_raises_when_missing(self, store: ExperienceStore) -> None:
        with pytest.raises(ExperienceNotFoundError):
            store.get("missing")

    def test_register_rejects_invalid_type(self, store: ExperienceStore) -> None:
        with pytest.raises(InvalidExperienceError):
            store.register("not-an-experience")  # type: ignore[arg-type]

    def test_get_all_and_get_by_capability(self, store: ExperienceStore) -> None:
        store.register(_make_experience(experience_id="exp-1", capability_id="web.search"))
        store.register(_make_experience(experience_id="exp-2", capability_id="chat.respond"))

        assert len(store.get_all()) == 2
        assert {e.experience_id for e in store.get_by_capability("web.search")} == {"exp-1"}

    def test_aggregate_outcome_rate_returns_none_without_data(
        self, store: ExperienceStore
    ) -> None:
        assert store.aggregate_outcome_rate(capability_id="web.search") is None

    def test_aggregate_outcome_rate_computes_ratio(self, store: ExperienceStore) -> None:
        store.register(_make_experience(experience_id="e1", outcome=ExperienceOutcome.SUCCESS))
        store.register(_make_experience(experience_id="e2", outcome=ExperienceOutcome.SUCCESS))
        store.register(_make_experience(experience_id="e3", outcome=ExperienceOutcome.FAILURE))

        rate = store.aggregate_outcome_rate(capability_id="web.search")

        assert rate == pytest.approx(2 / 3)

    def test_aggregate_outcome_rate_filters_by_provider_and_model(
        self, store: ExperienceStore
    ) -> None:
        store.register(
            _make_experience(
                experience_id="e1", provider_id="provider.a", model_id="model.a",
                outcome=ExperienceOutcome.SUCCESS,
            )
        )
        store.register(
            _make_experience(
                experience_id="e2", provider_id="provider.b", model_id="model.b",
                outcome=ExperienceOutcome.FAILURE,
            )
        )

        rate_a = store.aggregate_outcome_rate(
            capability_id="web.search", provider_id="provider.a", model_id="model.a"
        )
        rate_b = store.aggregate_outcome_rate(
            capability_id="web.search", provider_id="provider.b", model_id="model.b"
        )

        assert rate_a == 1.0
        assert rate_b == 0.0

    def test_user_corrected_excluded_from_totals(self, store: ExperienceStore) -> None:
        store.register(
            _make_experience(experience_id="e1", outcome=ExperienceOutcome.SUCCESS)
        )
        store.register(
            _make_experience(experience_id="e2", outcome=ExperienceOutcome.USER_CORRECTED)
        )

        rate = store.aggregate_outcome_rate(capability_id="web.search")

        assert rate == 1.0


class TestExperienceRecorder:
    def _task(self, *, capability_id: str = "web.search", duration_seconds: float | None = 0.5) -> Task:
        return Task(
            id="task-1",
            status=TaskStatus.COMPLETED,
            request=TaskRequest(capability_id=capability_id),
            response=TaskResponse(duration_seconds=duration_seconds),
        )

    def test_records_success_on_task_completed(
        self, store: ExperienceStore, event_bus: EventBus
    ) -> None:
        recorder = ExperienceRecorder(event_bus, store)
        recorder.initialize()

        event_bus.publish(TASK_COMPLETED_EVENT, TaskCompletedEvent(task=self._task()))

        experiences = store.get_by_capability("web.search")
        assert len(experiences) == 1
        assert experiences[0].outcome is ExperienceOutcome.SUCCESS
        assert experiences[0].latency_ms == 500.0

    def test_records_provider_and_model_id_from_response_metadata(
        self, store: ExperienceStore, event_bus: EventBus
    ) -> None:
        """
        Regression test: closes the previously documented "no
        provider_id/model_id available" limitation now that
        CapabilityExecutor populates `TaskResponse.metadata` for
        provider-backed capabilities.
        """

        recorder = ExperienceRecorder(event_bus, store)
        recorder.initialize()

        task = Task(
            id="task-2",
            status=TaskStatus.COMPLETED,
            request=TaskRequest(capability_id="chat.respond"),
            response=TaskResponse(
                duration_seconds=0.2,
                metadata={"provider_id": "provider.ollama", "model_id": "llama3"},
            ),
        )
        event_bus.publish(TASK_COMPLETED_EVENT, TaskCompletedEvent(task=task))

        experiences = store.get_by_capability("chat.respond")
        assert len(experiences) == 1
        assert experiences[0].provider_id == "provider.ollama"
        assert experiences[0].model_id == "llama3"

    def test_records_failure_on_task_failed(
        self, store: ExperienceStore, event_bus: EventBus
    ) -> None:
        recorder = ExperienceRecorder(event_bus, store)
        recorder.initialize()

        failed_task = Task(
            id="task-2",
            status=TaskStatus.FAILED,
            request=TaskRequest(capability_id="web.search"),
            failure=RuntimeError("boom"),
        )
        event_bus.publish(TASK_FAILED_EVENT, TaskFailedEvent(task=failed_task))

        experiences = store.get_by_capability("web.search")
        assert len(experiences) == 1
        assert experiences[0].outcome is ExperienceOutcome.FAILURE

    def test_shutdown_unsubscribes(self, store: ExperienceStore, event_bus: EventBus) -> None:
        recorder = ExperienceRecorder(event_bus, store)
        recorder.initialize()
        recorder.shutdown()

        event_bus.publish(TASK_COMPLETED_EVENT, TaskCompletedEvent(task=self._task()))

        assert store.get_by_capability("web.search") == ()


class TestExperienceModuleDriver:
    def test_start_and_stop_wire_recorder(
        self, store: ExperienceStore, event_bus: EventBus
    ) -> None:
        driver = ExperienceModuleDriver(experience_store=store, event_bus=event_bus)

        driver.start()
        event_bus.publish(
            TASK_COMPLETED_EVENT,
            TaskCompletedEvent(
                task=Task(
                    id="t1",
                    status=TaskStatus.COMPLETED,
                    request=TaskRequest(capability_id="chat.respond"),
                    response=TaskResponse(duration_seconds=0.1),
                )
            ),
        )
        assert len(store.get_by_capability("chat.respond")) == 1

        driver.stop()
        event_bus.publish(
            TASK_COMPLETED_EVENT,
            TaskCompletedEvent(
                task=Task(
                    id="t2",
                    status=TaskStatus.COMPLETED,
                    request=TaskRequest(capability_id="chat.respond"),
                    response=TaskResponse(duration_seconds=0.1),
                )
            ),
        )
        # Still just 1 -- driver.stop() unsubscribed the recorder.
        assert len(store.get_by_capability("chat.respond")) == 1

    def test_health_check_reports_healthy(
        self, store: ExperienceStore, event_bus: EventBus
    ) -> None:
        driver = ExperienceModuleDriver(experience_store=store, event_bus=event_bus)

        result = driver._check_health()

        assert result.status.name == "HEALTHY"
