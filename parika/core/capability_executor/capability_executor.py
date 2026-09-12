"""
PARIKA Core - CapabilityExecutor Component

This module implements the CapabilityExecutor, the core component
responsible for executing resolved capabilities by delegating execution
to either ToolManager or ProviderManager.

CapabilityExecutor does not perform capability planning, backend
selection, or request construction. Those responsibilities belong to
upstream core components.

Responsibilities
----------------
- Validate execution requests.
- Publish capability execution lifecycle events.
- Delegate execution to ToolManager or ProviderManager.
- Measure execution duration.
- Return immutable CapabilityExecutionResponse objects.
- Wrap backend exceptions as CapabilityExecutionError.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any, cast

from parika.core.tool_manager.request import ToolRequest
from parika.core.provider_manager.request import ProviderRequest
from parika.core.provider_manager.exceptions import (
    ProviderConnectionError,
    ProviderTimeoutError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderModelNotFoundError,
    ProviderAuthenticationError,
    ProviderAuthorizationError,
    ProviderResponseError,
)
from parika.core.provider_manager.provider_model import ProviderModel
from parika.core.planner.model_selection.routing_config import load_routing_config
from parika.core.configuration.configuration import Configuration
from parika.core.event_bus.event_bus import EventBus
from parika.core.logger.logger import Logger

from .events import (
    CapabilityExecutionCompletedEvent,
    CapabilityExecutionFailedEvent,
    CapabilityExecutionStartedEvent,
)
from parika.core.capability_executor.execution_backend import (
    ExecutionBackend,
)
from .exceptions import (
    CapabilityExecutionError,
    InvalidCapabilityExecutionRequestError,
)
from .request import (
    CapabilityExecutionRequest,
)
from .response import (
    CapabilityExecutionResponse,
)

from parika.core.provider_manager.provider_manager import (
    ProviderManager,
)

from parika.core.tool_manager.tool_manager import (
    ToolManager,
)


class CapabilityExecutor:
    """
    Executes resolved capabilities.

    CapabilityExecutor is responsible only for execution.

    It receives an immutable CapabilityExecutionRequest prepared by
    upstream components, publishes execution lifecycle events, delegates
    execution to the appropriate backend manager, and returns an
    immutable CapabilityExecutionResponse.

    CapabilityExecutor intentionally does not:

    - Resolve capabilities.
    - Select execution backends.
    - Select provider models.
    - Construct backend requests.
    - Interpret execution results.
    """

    def __init__(
        self,
        event_bus: EventBus,
        logger: Logger,
        tool_manager: ToolManager,
        provider_manager: ProviderManager,
        configuration: Configuration | None = None,
    ) -> None:
        """
        Initialize the CapabilityExecutor.

        Args:
            event_bus:
                EventBus used to publish execution lifecycle events.

            logger:
                PARIKA Logger component.

            tool_manager:
                ToolManager responsible for tool execution.

            provider_manager:
                ProviderManager responsible for provider execution.

            configuration:
                Optional Configuration, used for routing config in chat.respond
                provider fallback.
        """

        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._tool_manager = tool_manager
        self._provider_manager = provider_manager
        self._configuration = configuration

        self._logger.debug(
            "CapabilityExecutor initialized."
        )

    def execute(
        self,
        request: CapabilityExecutionRequest,
        *,
        task_id: str | None = None,
    ) -> CapabilityExecutionResponse:
        """
        Execute a capability.

        Args:
            request:
                Immutable execution request.

            task_id:
                Optional identifier of the owning `TaskManager` `Task`
                (Phase 3.5b), forwarded unchanged onto every published
                `CapabilityExecution*Event` so a subscriber can
                correlate this execution to its owning Task and to its
                own Started/Completed/Failed events. Purely additive;
                omitting it (the previous, still-supported behavior)
                simply leaves `task_id` `None` on the published events.

        Returns:
            CapabilityExecutionResponse.

        Raises:
            InvalidCapabilityExecutionRequestError:
                If the request is invalid.

            CapabilityExecutionError:
                If execution fails.
        """

        self._validate_request(request)

        definition = request.resolution.definition

        capability_id = definition.id
        capability_category = definition.category
        backend = request.target.backend

        self._event_bus.publish(
             "capability.execution.started",
            CapabilityExecutionStartedEvent(
                capability_id=capability_id,
                capability_category=capability_category,
                backend=backend,
                task_id=task_id,
            )
        )

        self._logger.debug(
            "Executing capability '%s' using backend '%s'.",
            capability_id,
            backend,
        )

        started_at = perf_counter()

        response_metadata: dict[str, Any] = {}

        try:

            if backend is ExecutionBackend.TOOL:

                tool_request = cast(
                    ToolRequest,
                    request.backend_request,
                )

                backend_response = self._tool_manager.execute(
                    tool_id=request.target.identifier,
                    request=tool_request,
                )

            elif backend is ExecutionBackend.PROVIDER:

                provider_request = cast(
                    ProviderRequest,
                    request.backend_request,
                )

                model = request.target.model
                assert model is not None

                # === CHAT.RESPOND-SPECIFIC PROVIDER FALLBACK ===
                if capability_id == "chat.respond":
                    backend_response = self._execute_chat_respond_with_fallback(
                        provider_id=request.target.identifier,
                        model=model,
                        request=provider_request,
                        capability_id=capability_id,
                        capability_category=capability_category,
                    )
                else:
                    # All other capabilities: single attempt, no fallback
                    backend_response = self._provider_manager.execute(
                        provider_id=request.target.identifier,
                        model=model,
                        request=provider_request,
                    )

                # Surfaces which provider/model actually served this
                # request -- e.g. for the CLI's `/status` diagnostics
                # and Experience's provider_id/model_id fields (see
                # `parika/modules/experience/recorder.py`'s previously
                # documented data-availability limitation). Purely
                # additive metadata; CapabilityExecutor still never
                # interprets or modifies backend_response itself.
                response_metadata["provider_id"] = request.target.identifier
                response_metadata["model_id"] = model.id

            else:
                raise CapabilityExecutionError(
                    f"Unsupported execution backend: {backend!r}"
                )

            duration_seconds = (
                perf_counter() - started_at
            )

            response = CapabilityExecutionResponse(
                backend_response=backend_response,
                metadata=response_metadata,
                duration_seconds=duration_seconds,
            )

            self._event_bus.publish(
                "capability.execution.completed",
                CapabilityExecutionCompletedEvent(
                    capability_id=capability_id,
                    capability_category=capability_category,
                    backend=backend,
                    duration_seconds=duration_seconds,
                    task_id=task_id,
                )
            )

            self._logger.debug(
                (
                    "Capability '%s' executed successfully "
                    "using backend '%s' in %.6f seconds."
                ),
                capability_id,
                backend,
                duration_seconds,
            )

            return response

        except Exception as ex:

            try:
                self._event_bus.publish(
                    "capability.execution.failed",
                    CapabilityExecutionFailedEvent(
                        capability_id=capability_id,
                        capability_category=capability_category,
                        backend=backend,
                        error_type=type(ex).__name__,
                        error_message=str(ex),
                        task_id=task_id,
                    )
                )

            except Exception:
                self._logger.exception(
                    "Failed to publish capability.execution.failed event."
                )

            self._logger.exception(
                "Capability execution failed for '%s'.",
                capability_id,
            )

            raise CapabilityExecutionError(
                (
                    f"Capability execution failed for "
                    f"'{capability_id}'."
                )
            ) from ex

    def _validate_request(
        self,
        request: CapabilityExecutionRequest,
    ) -> None:
        """
        Validate an execution request.

        Args:
            request:
                Request to validate.

        Raises:
            InvalidCapabilityExecutionRequestError:
                If the request is invalid.
        """

        if not isinstance(
            request,
            CapabilityExecutionRequest,
        ):
            raise InvalidCapabilityExecutionRequestError(
                "Expected CapabilityExecutionRequest."
            )

    def _execute_chat_respond_with_fallback(
        self,
        provider_id: str,
        model: ProviderModel,
        request: ProviderRequest,
        capability_id: str,
        capability_category: Any,
    ) -> Any:
        """
        Execute chat.respond with provider fallback chain.

        Initial attempt uses the Planner-selected provider/model (remembered from GoalDecomposer).
        On fallback-triggering failure, restarts from PRIMARY and advances through
        SECONDARY -> FALLBACK -> LOCAL fixed model.
        """
        routing_config = load_routing_config(self._configuration)
        providers = {p.id: p for p in self._provider_manager.get_all()}

        # Build the provider chain in order: PRIMARY -> SECONDARY -> FALLBACK -> LOCAL
        chain: list[tuple[str | None, str | None]] = []  # (provider_id, model_id or None for first model)

        if routing_config.routing_type == "cloud":
            if routing_config.cloud_primary_provider:
                chain.append((routing_config.cloud_primary_provider, None))
            if routing_config.cloud_secondary_provider:
                chain.append((routing_config.cloud_secondary_provider, None))
            if routing_config.cloud_fallback_provider:
                chain.append((routing_config.cloud_fallback_provider, None))

        # Local fixed model as final fallback
        if routing_config.fixed_provider_id and routing_config.fixed_model_id:
            chain.append((routing_config.fixed_provider_id, routing_config.fixed_model_id))
        elif routing_config.fixed_model_id:
            chain.append((None, routing_config.fixed_model_id))  # Search all providers

        max_retries_per_provider = 1
        attempted_models: set[tuple[str, str]] = set()
        last_exception: BaseException | None = None

        # Start with the Planner-selected (remembered) provider/model as optimization attempt
        initial_provider_id = provider_id
        initial_model = model

        # Try optimization attempt first (no retry - it's an optimization)
        optimization_key = (initial_provider_id, initial_model.id)
        attempted_models.add(optimization_key)

        try:
            response = self._provider_manager.execute(
                provider_id=initial_provider_id,
                model=initial_model,
                request=request,
            )
            self._logger.debug(
                "chat.respond synthesis succeeded on remembered provider: provider=%s model=%s",
                initial_provider_id, initial_model.id
            )
            return response
        except Exception as ex:
            last_exception = ex
            self._logger.warning(
                "chat.respond remembered provider failed (optimization): provider=%s model=%s error=%s. Restarting chain.",
                initial_provider_id, initial_model.id, ex
            )
            # Fall through to full chain restart

        # RESTART: iterate full chain from PRIMARY
        for chain_provider_id, chain_model_id in chain:
            # Resolve provider
            if chain_provider_id is not None:
                if chain_provider_id not in providers:
                    continue
                provider = providers[chain_provider_id]
            else:
                # Search all providers for the model
                provider = None
                for p in providers.values():
                    for m in p.models:
                        if m.id == chain_model_id:
                            provider = p
                            break
                    if provider:
                        break
                if provider is None:
                    continue

            # Resolve model
            if chain_model_id is None:
                if not provider.models:
                    continue
                candidate_model = provider.models[0]
            else:
                candidate_model = next(
                    (m for m in provider.models if m.id == chain_model_id),
                    None
                )
                if candidate_model is None:
                    continue

            candidate_key = (provider.id, candidate_model.id)

            # Skip if already attempted (including optimization attempt)
            if candidate_key in attempted_models:
                continue

            attempted_models.add(candidate_key)

            # Per-provider retry loop for transport errors
            for attempt in range(max_retries_per_provider + 1):
                try:
                    response = self._provider_manager.execute(
                        provider_id=provider.id,
                        model=candidate_model,
                        request=request,
                    )
                    self._logger.debug(
                        "chat.respond synthesis succeeded on fallback provider: provider=%s model=%s",
                        provider.id, candidate_model.id
                    )
                    return response

                except Exception as ex:
                    last_exception = ex

                    # Transport errors: retry if attempts remain
                    if isinstance(ex, (
                        ProviderConnectionError, ProviderTimeoutError,
                        ProviderRateLimitError, ProviderServerError,
                        ProviderModelNotFoundError,
                    )):
                        if attempt < max_retries_per_provider:
                            continue
                        # Retries exhausted - advance chain
                        break

                    # ProviderResponseError (includes OpenAICompatibleResponseError / HTTP 400): advance chain
                    if isinstance(ex, ProviderResponseError):
                        break

                    # Auth/Authorization errors: do NOT advance chain (config issue)
                    if isinstance(ex, (ProviderAuthenticationError, ProviderAuthorizationError)):
                        raise

                    # Other unexpected errors: advance chain
                    break

            # Current provider failed - continue to next in chain
            continue

        # All providers exhausted
        raise CapabilityExecutionError(
            f"chat.respond synthesis failed after exhausting provider chain: {last_exception}"
        ) from last_exception