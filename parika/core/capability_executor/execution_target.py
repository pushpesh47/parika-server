"""
PARIKA Capability Execution Target.

Defines the immutable execution target used by CapabilityExecutor
to determine where a capability should be executed.
"""

from __future__ import annotations

from dataclasses import dataclass

from parika.core.provider_manager import ProviderModel

from .exceptions import InvalidExecutionTargetError
from .execution_backend import ExecutionBackend


@dataclass(frozen=True, slots=True)
class ExecutionTarget:
    """
    Immutable execution target.

    Attributes:
        backend:
            Execution backend to use.

        identifier:
            Backend-specific identifier.

            TOOL:
                Tool identifier.

            PROVIDER:
                Provider identifier.

        model:
            Provider model selected for execution.

            Only applicable when backend is PROVIDER.
    """

    backend: ExecutionBackend

    identifier: str

    model: ProviderModel | None = None

    def __post_init__(self) -> None:
        """
        Validate the execution target.

        Ensures the selected backend is supplied with the required
        execution information and rejects invalid backend/model
        combinations.
        """

        if self.backend is ExecutionBackend.TOOL:
            if self.model is not None:
                raise InvalidExecutionTargetError(
                    "model must be None for TOOL execution."
                )

        elif self.backend is ExecutionBackend.PROVIDER:
            if self.model is None:
                raise InvalidExecutionTargetError(
                    "model is required for PROVIDER execution."
                )

        else:
            raise InvalidExecutionTargetError(
                f"Unsupported execution backend: {self.backend!r}."
            )