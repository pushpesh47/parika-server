"""
PARIKA Remote Execution Backend (Placeholder)

Implements ExecutionBackend for remote execution (future).
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
from parika.core.logger.logger import Logger


class RemoteBackend(ExecutionBackend):
    """
    Remote execution backend (placeholder).
    
    This is a placeholder for future remote execution support.
    Raises NotImplementedError for all operations.
    """

    def __init__(
        self,
        *,
        logger: Logger,
    ) -> None:
        self._logger = logger.get_logger(__name__)

    @property
    def backend_type(self) -> str:
        return "remote"

    async def execute(
        self,
        strategy: ExecutionStrategy,
        inputs: MappingProxyType[str, Any],
        context: BackendExecutionContext,
    ) -> BackendExecutionResult:
        """Execute a capability remotely (not implemented)."""
        self._logger.error(
            "Remote backend execution not implemented for capability '%s'",
            strategy.capability_id
        )
        return BackendExecutionResult(
            success=False,
            error="Remote execution not implemented",
        )

    def is_available(self) -> bool:
        """Remote backend is not available."""
        return False

    async def health_check(self) -> bool:
        """Health check - remote backend is not available."""
        return False