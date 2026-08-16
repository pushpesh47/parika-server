"""
Unit tests for ProviderManager.

These tests exercise ProviderManager against a small concrete
`_FakeProviderDriver` (following the same pattern already used in
`tests/core/planner/test_planner.py`) so that registration, model
discovery, health refresh, and request execution are all verified
against the real `Provider`/`ProviderModel` domain objects rather than
mocks.

NOTE (known, pre-existing issue - not introduced by these tests):
`ProviderModel.metadata` defaults to a plain mutable `dict`
(`provider_model.py:65`) instead of an immutable `MappingProxyType`
like `Provider.metadata` (`provider.py:75-77`) and `ProviderResponse.metadata`
(`response.py:37-39`) both do. Because dataclass-generated `__hash__`
hashes a tuple of all field values, and `dict` is unhashable, every
`ProviderModel` instance is unhashable:

    >>> hash(ProviderModel(id="m1", name="M1"))
    TypeError: unhashable type: 'dict'

This means real `ProviderModel` instances can never be placed inside a
`frozenset`, even though `Provider.models` is typed as
`frozenset[ProviderModel]`. Dataclass field types are not enforced at
runtime, so throughout this file (and in `test_provider.py`) a plain
`tuple(...)` of `ProviderModel` instances is used wherever a
`Provider.models` value is needed, with a `# type: ignore[arg-type]`
comment - exactly the workaround already documented in
`tests/core/planner/test_planner.py::_register_llm_capability`. This
also means `model.metadata` can be mutated in place after construction
despite the dataclass being `frozen=True`, since frozen only blocks
attribute *reassignment*, not mutation of a mutable field's contents.
This is not fixed here per task instructions; see
`test_provider.py::TestProviderModel` for dedicated tests documenting
it.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger
from parika.core.provider_manager.driver import ProviderDriver
from parika.core.provider_manager.exceptions import (
    ProviderConnectionError,
    ProviderExecutionError,
    ProviderModelNotFoundError,
    ProviderRegistrationError,
    ProviderTimeoutError,
)
from parika.core.provider_manager.model_capability import ModelCapability
from parika.core.provider_manager.provider import Provider
from parika.core.provider_manager.provider_health import ProviderHealth
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.response import ProviderResponse
from parika.core.state_manager.states import ProviderState


class RecordingSubscriber:
    """
    EventBus subscriber that records every payload it receives.
    """

    def __init__(self) -> None:
        self.received: list[Any] = []

    def __call__(self, payload: Any) -> None:
        self.received.append(payload)


class _FakeProviderDriver(ProviderDriver):
    """
    Minimal configurable `ProviderDriver` fake.

    Each of the three abstract operations can either return a
    preconfigured value or raise a preconfigured exception, and every
    call is recorded so tests can assert on delegation.
    """

    def __init__(
        self,
        *,
        models: frozenset[ProviderModel] | None = None,
        models_error: Exception | None = None,
        health: ProviderHealth | None = None,
        health_error: Exception | None = None,
        response: ProviderResponse | None = None,
        execute_error: Exception | None = None,
    ) -> None:
        self._models = models if models is not None else frozenset()
        self._models_error = models_error

        self._health = (
            health if health is not None else ProviderHealth(available=True)
        )
        self._health_error = health_error

        self._response = response
        self._execute_error = execute_error

        self.discover_models_calls = 0
        self.check_health_calls = 0
        self.execute_calls: list[tuple[ProviderModel, ProviderRequest]] = []

    def discover_models(self) -> frozenset[ProviderModel]:
        self.discover_models_calls += 1

        if self._models_error is not None:
            raise self._models_error

        return self._models

    def check_health(self) -> ProviderHealth:
        self.check_health_calls += 1

        if self._health_error is not None:
            raise self._health_error

        return self._health

    def execute(
        self,
        model: ProviderModel,
        request: ProviderRequest,
    ) -> ProviderResponse:
        self.execute_calls.append((model, request))

        if self._execute_error is not None:
            raise self._execute_error

        assert self._response is not None
        return self._response


@pytest.fixture
def provider_manager(event_bus: EventBus, logger: Logger) -> ProviderManager:
    return ProviderManager(event_bus=event_bus, logger=logger)


def _make_model(
    model_id: str = "model-1",
    *,
    capabilities: frozenset[ModelCapability] = frozenset(),
) -> ProviderModel:
    return ProviderModel(
        id=model_id,
        name=model_id,
        capabilities=capabilities,
    )


def _make_provider(
    provider_id: str = "provider.test",
    *,
    models: tuple[ProviderModel, ...] = (),
    state: ProviderState = ProviderState.DISCONNECTED,
    enabled: bool = True,
) -> Provider:
    return Provider(
        id=provider_id,
        name=provider_id,
        state=state,
        enabled=enabled,
        # NOTE: see the module docstring - ProviderModel is unhashable,
        # so a real frozenset(...) of models cannot be constructed. A
        # tuple is used instead; Provider.models is not runtime-checked.
        models=models,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------


class TestRegister:
    def test_registers_provider_and_driver(
        self,
        provider_manager: ProviderManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("provider.registered", subscriber)

        provider = _make_provider("provider.ollama")
        driver = _FakeProviderDriver()

        provider_manager.register(provider, driver)

        assert provider_manager.contains("provider.ollama")
        assert provider_manager.get("provider.ollama") is provider
        assert len(subscriber.received) == 1
        assert subscriber.received[0] == {"provider_id": "provider.ollama"}

    def test_rejects_duplicate_registration(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        provider = _make_provider("provider.ollama")

        provider_manager.register(provider, _FakeProviderDriver())

        with pytest.raises(ProviderRegistrationError):
            provider_manager.register(provider, _FakeProviderDriver())

    def test_duplicate_registration_does_not_replace_existing_driver(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        provider = _make_provider("provider.ollama")
        first_driver = _FakeProviderDriver()

        provider_manager.register(provider, first_driver)

        with pytest.raises(ProviderRegistrationError):
            provider_manager.register(provider, _FakeProviderDriver())

        # The originally registered driver must still be the one used.
        provider_manager.discover_models("provider.ollama")
        assert first_driver.discover_models_calls == 1

    def test_register_performs_no_type_validation(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        """
        Document actual current behavior: `register()` performs no
        `isinstance`/type checks on either argument (verified by
        reading `provider_manager.py`). Passing an object that merely
        duck-types an `.id` attribute is silently accepted rather than
        rejected with a `TypeError`, and it is stored/retrievable like
        any other provider.
        """

        class _NotAProvider:
            id = "duck.typed"

        fake_provider = _NotAProvider()
        driver = _FakeProviderDriver()

        provider_manager.register(fake_provider, driver)  # type: ignore[arg-type]

        assert provider_manager.contains("duck.typed")
        assert provider_manager.get("duck.typed") is fake_provider


# ---------------------------------------------------------------------
# unregister()
# ---------------------------------------------------------------------


class TestUnregister:
    def test_unregister_removes_provider_and_driver(
        self,
        provider_manager: ProviderManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("provider.unregistered", subscriber)

        provider_manager.register(
            _make_provider("provider.ollama"), _FakeProviderDriver()
        )

        provider_manager.unregister("provider.ollama")

        assert not provider_manager.contains("provider.ollama")
        assert len(subscriber.received) == 1
        assert subscriber.received[0] == {"provider_id": "provider.ollama"}

    def test_unregister_raises_when_missing(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        with pytest.raises(ProviderRegistrationError):
            provider_manager.unregister("missing")

    def test_unregister_then_execute_raises_not_registered(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        provider_manager.register(
            _make_provider("provider.ollama"), _FakeProviderDriver()
        )
        provider_manager.unregister("provider.ollama")

        with pytest.raises(ProviderRegistrationError):
            provider_manager.execute(
                "provider.ollama", _make_model(), ProviderRequest()
            )


# ---------------------------------------------------------------------
# get() / contains() / get_all() / count()
# ---------------------------------------------------------------------


class TestLookup:
    def test_get_raises_when_missing(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        with pytest.raises(ProviderRegistrationError):
            provider_manager.get("missing")

    def test_contains_false_when_missing(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        assert not provider_manager.contains("missing")

    def test_get_all_and_count(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        provider_manager.register(
            _make_provider("provider.a"), _FakeProviderDriver()
        )
        provider_manager.register(
            _make_provider("provider.b"), _FakeProviderDriver()
        )

        assert provider_manager.count() == 2
        assert {p.id for p in provider_manager.get_all()} == {
            "provider.a",
            "provider.b",
        }

    def test_get_all_is_empty_initially(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        assert provider_manager.get_all() == ()
        assert provider_manager.count() == 0


# ---------------------------------------------------------------------
# discover_models()
# ---------------------------------------------------------------------


class TestDiscoverModels:
    def test_discover_models_updates_provider_and_publishes_event(
        self,
        provider_manager: ProviderManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("provider.models_discovered", subscriber)

        model = _make_model("llama3")
        driver = _FakeProviderDriver(models=(model,))  # type: ignore[arg-type]
        provider_manager.register(_make_provider("provider.ollama"), driver)

        updated = provider_manager.discover_models("provider.ollama")

        assert updated.models == (model,)
        assert provider_manager.get("provider.ollama").models == (model,)
        assert len(subscriber.received) == 1
        assert subscriber.received[0] == {
            "provider_id": "provider.ollama",
            "model_count": 1,
        }

    def test_discover_models_returns_new_provider_instance(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        original = _make_provider("provider.ollama")
        provider_manager.register(original, _FakeProviderDriver())

        updated = provider_manager.discover_models("provider.ollama")

        # Provider is immutable/frozen; discovery must produce a new
        # instance via dataclasses.replace rather than mutating.
        assert updated is not original
        assert updated.id == original.id

    def test_discover_models_raises_when_provider_not_registered(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        with pytest.raises(ProviderRegistrationError):
            provider_manager.discover_models("missing")

    def test_discover_models_propagates_driver_exception_unwrapped(
        self,
        provider_manager: ProviderManager,
        event_bus: EventBus,
    ) -> None:
        """
        `discover_models()` calls `driver.discover_models()` with no
        surrounding try/except (verified by reading
        `provider_manager.py`), so whatever exception the driver
        raises propagates to the caller completely unwrapped - it is
        NOT translated into `ProviderExecutionError` despite that
        being documented as a possibility in the method's docstring.
        """

        subscriber = RecordingSubscriber()
        event_bus.subscribe("provider.models_discovered", subscriber)

        driver = _FakeProviderDriver(
            models_error=ProviderConnectionError("unreachable")
        )
        provider_manager.register(_make_provider("provider.ollama"), driver)

        with pytest.raises(ProviderConnectionError):
            provider_manager.discover_models("provider.ollama")

        # No event published and no stored-provider mutation on failure.
        assert subscriber.received == []
        assert provider_manager.get("provider.ollama").models == ()


# ---------------------------------------------------------------------
# refresh_health()
# ---------------------------------------------------------------------


class TestRefreshHealth:
    def test_refresh_health_updates_provider_and_publishes_event(
        self,
        provider_manager: ProviderManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("provider.health_updated", subscriber)

        health = ProviderHealth(available=True, latency_ms=12.5)
        driver = _FakeProviderDriver(health=health)
        provider_manager.register(_make_provider("provider.ollama"), driver)

        updated = provider_manager.refresh_health("provider.ollama")

        assert updated.health == health
        assert provider_manager.get("provider.ollama").health == health
        assert len(subscriber.received) == 1
        assert subscriber.received[0] == {
            "provider_id": "provider.ollama",
            "available": True,
            "latency_ms": 12.5,
        }

    def test_refresh_health_raises_when_provider_not_registered(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        with pytest.raises(ProviderRegistrationError):
            provider_manager.refresh_health("missing")

    def test_refresh_health_propagates_driver_exception_unwrapped(
        self,
        provider_manager: ProviderManager,
        event_bus: EventBus,
    ) -> None:
        subscriber = RecordingSubscriber()
        event_bus.subscribe("provider.health_updated", subscriber)

        driver = _FakeProviderDriver(
            health_error=ProviderTimeoutError("timed out")
        )
        provider_manager.register(_make_provider("provider.ollama"), driver)

        with pytest.raises(ProviderTimeoutError):
            provider_manager.refresh_health("provider.ollama")

        assert subscriber.received == []
        assert provider_manager.get("provider.ollama").health is None


# ---------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------


class TestExecute:
    def test_execute_delegates_to_driver_and_returns_response(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        model = _make_model("llama3")
        response = ProviderResponse(model_id="llama3")
        driver = _FakeProviderDriver(response=response)
        provider_manager.register(
            _make_provider("provider.ollama", models=(model,)), driver
        )

        request = ProviderRequest()
        result = provider_manager.execute("provider.ollama", model, request)

        assert result is response
        assert driver.execute_calls == [(model, request)]

    def test_execute_raises_when_provider_not_registered(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        with pytest.raises(ProviderRegistrationError):
            provider_manager.execute(
                "missing", _make_model(), ProviderRequest()
            )

    def test_execute_raises_when_model_not_registered_for_provider(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        registered_model = _make_model("llama3")
        other_model = _make_model("mistral")
        driver = _FakeProviderDriver()
        provider_manager.register(
            _make_provider("provider.ollama", models=(registered_model,)),
            driver,
        )

        with pytest.raises(ProviderModelNotFoundError):
            provider_manager.execute(
                "provider.ollama", other_model, ProviderRequest()
            )

        # Driver must not be invoked when the model check fails first.
        assert driver.execute_calls == []

    def test_execute_propagates_driver_exception_unwrapped(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        """
        `execute()` calls `driver.execute(...)` directly with no
        try/except, so a `ProviderExecutionError` (or any other
        exception) raised by the driver propagates to the caller as-is
        - it is not caught, re-wrapped, or translated.
        """

        model = _make_model("llama3")
        driver = _FakeProviderDriver(
            execute_error=ProviderExecutionError("execution failed")
        )
        provider_manager.register(
            _make_provider("provider.ollama", models=(model,)), driver
        )

        with pytest.raises(ProviderExecutionError):
            provider_manager.execute(
                "provider.ollama", model, ProviderRequest()
            )


# ---------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_register_of_distinct_providers(
        self,
        provider_manager: ProviderManager,
    ) -> None:
        provider_count = 32
        errors: list[Exception] = []

        def _register(index: int) -> None:
            try:
                provider_manager.register(
                    _make_provider(f"provider.{index}"),
                    _FakeProviderDriver(),
                )
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [
            threading.Thread(target=_register, args=(i,))
            for i in range(provider_count)
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        assert provider_manager.count() == provider_count
        assert {p.id for p in provider_manager.get_all()} == {
            f"provider.{i}" for i in range(provider_count)
        }
