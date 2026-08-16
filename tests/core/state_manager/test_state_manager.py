"""
Unit tests for StateManager.
"""

from __future__ import annotations

import pytest

from parika.core.logger.logger import Logger
from parika.core.state_manager.state_manager import StateManager
from parika.core.state_manager.states import (
    ExecutionState,
    InteractionState,
    LifecycleState,
    ProviderState,
)


@pytest.fixture
def state_manager(logger: Logger) -> StateManager:
    return StateManager(logger)


# ---------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------


class TestDefaults:
    def test_default_lifecycle_state_is_stopped(
        self,
        state_manager: StateManager,
    ) -> None:
        assert state_manager.get_lifecycle_state() is LifecycleState.STOPPED

    def test_default_execution_state_is_idle(
        self,
        state_manager: StateManager,
    ) -> None:
        assert state_manager.get_execution_state() is ExecutionState.IDLE

    def test_default_interaction_state_is_idle(
        self,
        state_manager: StateManager,
    ) -> None:
        assert (
            state_manager.get_interaction_state() is InteractionState.IDLE
        )

    def test_default_provider_state_is_disconnected(
        self,
        state_manager: StateManager,
    ) -> None:
        assert (
            state_manager.get_provider_state() is ProviderState.DISCONNECTED
        )


# ---------------------------------------------------------------------
# Lifecycle state
# ---------------------------------------------------------------------


class TestLifecycleState:
    def test_set_and_get(self, state_manager: StateManager) -> None:
        state_manager.set_lifecycle_state(LifecycleState.RUNNING)

        assert state_manager.get_lifecycle_state() is LifecycleState.RUNNING

    def test_rejects_wrong_enum_type(
        self,
        state_manager: StateManager,
    ) -> None:
        with pytest.raises(TypeError):
            state_manager.set_lifecycle_state(ExecutionState.IDLE)  # type: ignore[arg-type]

    def test_rejects_non_enum_value(
        self,
        state_manager: StateManager,
    ) -> None:
        with pytest.raises(TypeError):
            state_manager.set_lifecycle_state("running")  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# Execution state
# ---------------------------------------------------------------------


class TestExecutionState:
    def test_set_and_get(self, state_manager: StateManager) -> None:
        state_manager.set_execution_state(ExecutionState.EXECUTING)

        assert (
            state_manager.get_execution_state() is ExecutionState.EXECUTING
        )

    def test_rejects_wrong_enum_type(
        self,
        state_manager: StateManager,
    ) -> None:
        with pytest.raises(TypeError):
            state_manager.set_execution_state(LifecycleState.RUNNING)  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# Interaction state
# ---------------------------------------------------------------------


class TestInteractionState:
    def test_set_and_get(self, state_manager: StateManager) -> None:
        state_manager.set_interaction_state(InteractionState.THINKING)

        assert (
            state_manager.get_interaction_state()
            is InteractionState.THINKING
        )

    def test_rejects_wrong_enum_type(
        self,
        state_manager: StateManager,
    ) -> None:
        with pytest.raises(TypeError):
            state_manager.set_interaction_state(ProviderState.CONNECTED)  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# Provider state
# ---------------------------------------------------------------------


class TestProviderState:
    def test_set_and_get(self, state_manager: StateManager) -> None:
        state_manager.set_provider_state(ProviderState.CONNECTED)

        assert (
            state_manager.get_provider_state() is ProviderState.CONNECTED
        )

    def test_rejects_wrong_enum_type(
        self,
        state_manager: StateManager,
    ) -> None:
        with pytest.raises(TypeError):
            state_manager.set_provider_state(InteractionState.IDLE)  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# Independence between state categories
# ---------------------------------------------------------------------


class TestStateIndependence:
    def test_changing_one_state_does_not_affect_others(
        self,
        state_manager: StateManager,
    ) -> None:
        state_manager.set_lifecycle_state(LifecycleState.RUNNING)

        assert state_manager.get_execution_state() is ExecutionState.IDLE
        assert (
            state_manager.get_interaction_state() is InteractionState.IDLE
        )
        assert (
            state_manager.get_provider_state() is ProviderState.DISCONNECTED
        )
