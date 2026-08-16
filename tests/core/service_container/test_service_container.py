"""
Unit tests for ServiceContainer.
"""

from __future__ import annotations

import threading

import pytest

from parika.core.service_container.service_container import (
    ServiceContainer,
)


class _ServiceA:
    pass


class _ServiceB:
    pass


@pytest.fixture
def service_container() -> ServiceContainer:
    return ServiceContainer()


# ---------------------------------------------------------------------
# register() / get() / has()
# ---------------------------------------------------------------------


class TestRegisterAndGet:
    def test_get_returns_registered_instance(
        self,
        service_container: ServiceContainer,
    ) -> None:
        instance = _ServiceA()

        service_container.register(_ServiceA, instance)

        assert service_container.get(_ServiceA) is instance

    def test_rejects_duplicate_registration(
        self,
        service_container: ServiceContainer,
    ) -> None:
        service_container.register(_ServiceA, _ServiceA())

        with pytest.raises(ValueError):
            service_container.register(_ServiceA, _ServiceA())

    def test_get_raises_when_not_registered(
        self,
        service_container: ServiceContainer,
    ) -> None:
        with pytest.raises(LookupError):
            service_container.get(_ServiceA)

    def test_has_reflects_registration_state(
        self,
        service_container: ServiceContainer,
    ) -> None:
        assert service_container.has(_ServiceA) is False

        service_container.register(_ServiceA, _ServiceA())

        assert service_container.has(_ServiceA) is True

    def test_different_service_types_are_independent(
        self,
        service_container: ServiceContainer,
    ) -> None:
        instance_a = _ServiceA()
        instance_b = _ServiceB()

        service_container.register(_ServiceA, instance_a)
        service_container.register(_ServiceB, instance_b)

        assert service_container.get(_ServiceA) is instance_a
        assert service_container.get(_ServiceB) is instance_b


# ---------------------------------------------------------------------
# all()
# ---------------------------------------------------------------------


class TestAll:
    def test_all_returns_every_registered_service(
        self,
        service_container: ServiceContainer,
    ) -> None:
        instance_a = _ServiceA()
        instance_b = _ServiceB()

        service_container.register(_ServiceA, instance_a)
        service_container.register(_ServiceB, instance_b)

        everything = service_container.all()

        assert dict(everything) == {
            _ServiceA: instance_a,
            _ServiceB: instance_b,
        }

    def test_all_returns_empty_mapping_when_nothing_registered(
        self,
        service_container: ServiceContainer,
    ) -> None:
        assert dict(service_container.all()) == {}

    def test_all_is_read_only(
        self,
        service_container: ServiceContainer,
    ) -> None:
        service_container.register(_ServiceA, _ServiceA())

        everything = service_container.all()

        with pytest.raises(TypeError):
            everything[_ServiceB] = _ServiceB()  # type: ignore[index]


# ---------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------


class TestClear:
    def test_clear_removes_all_services(
        self,
        service_container: ServiceContainer,
    ) -> None:
        service_container.register(_ServiceA, _ServiceA())

        service_container.clear()

        assert service_container.has(_ServiceA) is False
        assert dict(service_container.all()) == {}

    def test_container_can_be_reused_after_clear(
        self,
        service_container: ServiceContainer,
    ) -> None:
        service_container.register(_ServiceA, _ServiceA())
        service_container.clear()

        new_instance = _ServiceA()
        service_container.register(_ServiceA, new_instance)

        assert service_container.get(_ServiceA) is new_instance


# ---------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_registration_of_distinct_types_succeeds(
        self,
        service_container: ServiceContainer,
    ) -> None:
        service_types = [type(f"Service{i}", (), {}) for i in range(50)]
        errors: list[Exception] = []

        def _register(service_type: type) -> None:
            try:
                service_container.register(service_type, service_type())
            except Exception as ex:  # pragma: no cover - failure path
                errors.append(ex)

        threads = [
            threading.Thread(target=_register, args=(service_type,))
            for service_type in service_types
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        assert errors == []
        assert all(
            service_container.has(service_type)
            for service_type in service_types
        )
