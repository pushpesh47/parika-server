"""
PARIKA Autonomous Execution - Execution Dispatcher

Dispatches execution to the appropriate backend based on resolved strategy.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

from parika.core.autonomous.execution_backend import (
    BackendExecutionContext,
    BackendExecutionResult,
    ExecutionBackend,
)
from parika.core.autonomous.execution_strategy import ExecutionStrategy
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger


class ExecutionDispatcher:
    """
    Dispatches execution to the appropriate backend.
    
    Responsibilities:
    - Select backend based on ExecutionStrategy.backend
    - Pass execution context
    - Execute and return structured result
    - Does NOT select implementation or runtime - dispatches already-resolved strategy
    """

    def __init__(
        self,
        *,
        backends: dict[str, ExecutionBackend],
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        self._backends = backends
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

    def register_backend(self, backend: ExecutionBackend) -> None:
        """Register a backend."""
        self._backends[backend.backend_type] = backend

    def get_backend(self, backend_type: str) -> ExecutionBackend | None:
        """Get a backend by type."""
        return self._backends.get(backend_type)

    async def dispatch(
        self,
        strategy: ExecutionStrategy,
        inputs: MappingProxyType[str, Any],
        context: BackendExecutionContext,
    ) -> BackendExecutionResult:
        """
        Dispatch execution to the appropriate backend.
        
        Args:
            strategy: Resolved execution strategy (contains backend type)
            inputs: Capability inputs
            context: Execution context
            
        Returns:
            BackendExecutionResult
        """
        backend = self._backends.get(strategy.backend.value)
        if not backend:
            error_msg = f"No backend registered for execution backend: {strategy.backend.value}"
            self._logger.error(error_msg)
            return BackendExecutionResult(
                success=False,
                error=error_msg,
            )

        self._logger.info(
            "Dispatching execution: task=%s, capability=%s, backend=%s, env=%s",
            context.task_id, strategy.capability_id, strategy.backend.value, strategy.required_environment.value
        )

        # Publish dispatch event
        self._event_bus.publish("execution.dispatching", {
            "task_id": context.task_id,
            "mission_id": context.mission_id,
            "agent_id": context.agent_id,
            "capability_id": strategy.capability_id,
            "backend": strategy.backend.value,
            "required_environment": strategy.required_environment.value,
        })

        try:
            result = await backend.execute(strategy, inputs, context)

            self._event_bus.publish("execution.dispatched", {
                "task_id": context.task_id,
                "mission_id": context.mission_id,
                "agent_id": context.agent_id,
                "capability_id": strategy.capability_id,
                "backend": strategy.backend.value,
                "success": result.success,
            })

            return result

        except Exception as e:
            error_msg = f"Dispatch error: {e}"
            self._logger.exception(error_msg)
            
            self._event_bus.publish("execution.dispatch_failed", {
                "task_id": context.task_id,
                "mission_id": context.mission_id,
                "agent_id": context.agent_id,
                "capability_id": strategy.capability_id,
                "backend": strategy.backend.value,
                "error": str(e),
            })

            return BackendExecutionResult(
                success=False,
                error=error_msg,
            )

    def is_backend_available(self, backend_type: str) -> bool:
        """Check if a backend is available."""
        backend = self._backends.get(backend_type)
        if not backend:
            return False
        return backend.is_available()

    async def health_check_all(self) -> dict[str, bool]:
        """Health check all registered backends."""
        results = {}
        for backend_type, backend in self._backends.items():
            try:
                results[backend_type] = await backend.health_check()
            except Exception:
                results[backend_type] = False
        return results