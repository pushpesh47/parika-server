"""
State management service for PARIKA.

This module provides the central service responsible for maintaining
the current operational state of the running PARIKA instance.
"""

from __future__ import annotations

from parika.core.logger.logger import Logger

from .states import (
    ExecutionState,
    InteractionState,
    LifecycleState,
    ProviderState,
)


class StateManager:
    """
    Centralized operational state manager.

    The StateManager maintains the current operational state of the
    running PARIKA instance. It is responsible only for representing
    the application's current state and does not contain transition
    logic or business rules.
    """

    def __init__(self, logger: Logger) -> None:
        """
        Initialize the state manager.

        Args:
            logger:
                Application logger service.
        """

        self._logger = logger.get_logger(__name__)

        self._lifecycle_state = LifecycleState.STOPPED
        self._execution_state = ExecutionState.IDLE
        self._interaction_state = InteractionState.IDLE
        self._provider_state = ProviderState.DISCONNECTED

    def set_lifecycle_state(
        self,
        state: LifecycleState,
    ) -> None:
        """
        Update the current lifecycle state.

        Args:
            state:
                New lifecycle state.
        """

        if type(state) is not LifecycleState:
            raise TypeError("state must be an instance of LifecycleState.")

        self._lifecycle_state = state

    def get_lifecycle_state(self) -> LifecycleState:
        """
        Return the current lifecycle state.
        """

        return self._lifecycle_state

    def set_execution_state(
        self,
        state: ExecutionState,
    ) -> None:
        """
        Update the current execution state.

        Args:
            state:
                New execution state.
        """

        if type(state) is not ExecutionState:
            raise TypeError("state must be an instance of ExecutionState.")

        self._execution_state = state

    def get_execution_state(self) -> ExecutionState:
        """
        Return the current execution state.
        """

        return self._execution_state

    def set_interaction_state(
        self,
        state: InteractionState,
    ) -> None:
        """
        Update the current interaction state.

        Args:
            state:
                New interaction state.
        """

        if type(state) is not InteractionState:
            raise TypeError("state must be an instance of InteractionState.")

        self._interaction_state = state

    def get_interaction_state(self) -> InteractionState:
        """
        Return the current interaction state.
        """

        return self._interaction_state

    def set_provider_state(
        self,
        state: ProviderState,
    ) -> None:
        """
        Update the current provider state.

        Args:
            state:
                New provider state.
        """

        if type(state) is not ProviderState:
            raise TypeError("state must be an instance of ProviderState.")

        self._provider_state = state

    def get_provider_state(self) -> ProviderState:
        """
        Return the current provider state.
        """

        return self._provider_state