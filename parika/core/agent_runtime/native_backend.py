"""
PARIKA Native Execution Backend

Implements ExecutionBackend for PARIKA's native in-process execution.
"""

from __future__ import annotations

import asyncio
from types import MappingProxyType
from typing import Any

from parika.core.autonomous.execution_backend import (
    BackendExecutionContext,
    BackendExecutionResult,
    ExecutionBackend,
)
from parika.core.autonomous.execution_strategy import ExecutionStrategy, ExecutionBackend as BackendEnum
from parika.core.capability_executor.capability_executor import CapabilityExecutor
from parika.core.capability_executor.request import CapabilityExecutionRequest
from parika.core.capability_executor.execution_target import ExecutionTarget
from parika.core.capability_executor.execution_backend import ExecutionBackend as CoreExecutionBackend
from parika.core.capability_resolver.capability_request import CapabilityRequest
from parika.core.capability_resolver.capability_resolver import CapabilityResolver
from parika.core.planner.planner import Planner
from parika.core.planner.goal import Goal
from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.provider_manager.provider_manager import ProviderManager
from parika.core.logger.logger import Logger


class NativeBackend(ExecutionBackend):
    """
    Native PARIKA execution backend.
    
    Uses the existing PARIKA Core execution path:
    - TOOL capabilities -> ToolManager/CapabilityExecutor
    - PROVIDER capabilities -> Planner -> CapabilityExecutor
    """

    def __init__(
        self,
        *,
        capability_executor: CapabilityExecutor,
        tool_manager: ToolManager,
        provider_manager: ProviderManager,
        capability_resolver: CapabilityResolver,
        planner: Planner,
        logger: Logger,
    ) -> None:
        self._capability_executor = capability_executor
        self._tool_manager = tool_manager
        self._provider_manager = provider_manager
        self._capability_resolver = capability_resolver
        self._planner = planner
        self._logger = logger.get_logger(__name__)

    @property
    def backend_type(self) -> str:
        return "native"

    async def execute(
        self,
        strategy: ExecutionStrategy,
        inputs: MappingProxyType[str, Any],
        context: BackendExecutionContext,
    ) -> BackendExecutionResult:
        """Execute a capability using PARIKA's native execution path."""
        import time
        start_time = time.perf_counter()
        
        try:
            self._logger.info(
                "Native backend executing capability '%s' for task '%s'",
                strategy.capability_id, context.task_id
            )

            # Resolve capability to get definition/category
            capability_resolution = self._capability_resolver.resolve(
                CapabilityRequest(capability_id=strategy.capability_id, metadata=context.permission_context)
            )

            category = capability_resolution.definition.category.value

            if category == "tool":
                result = await self._execute_tool(strategy, inputs, context, capability_resolution)
            else:
                result = await self._execute_provider(strategy, inputs, context, capability_resolution)

            execution_time_ms = (time.perf_counter() - start_time) * 1000
            
            return BackendExecutionResult(
                success=True,
                result=result,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            self._logger.exception(
                "Native backend execution failed for capability '%s': %s",
                strategy.capability_id, e
            )
            return BackendExecutionResult(
                success=False,
                error=str(e),
                execution_time_ms=execution_time_ms,
            )

    async def _execute_tool(
        self,
        strategy: ExecutionStrategy,
        inputs: MappingProxyType[str, Any],
        context: BackendExecutionContext,
        capability_resolution,
    ) -> MappingProxyType[str, Any]:
        """Execute a TOOL capability."""
        # Find the tool for this capability
        tool = None
        tools = self._tool_manager.get_all()
        for t in tools:
            if t.enabled and strategy.capability_id in t.capabilities:
                tool = t
                break

        if tool is None:
            raise ValueError(f"No enabled tool implements capability '{strategy.capability_id}'")

        # Build execution request
        tool_request = ToolRequest(
            arguments=inputs,
            metadata=context.permission_context,
        )

        target = ExecutionTarget(
            backend=CoreExecutionBackend.TOOL,
            identifier=tool.id,
        )

        execution_request = CapabilityExecutionRequest(
            resolution=capability_resolution,
            target=target,
            backend_request=tool_request,
            metadata=context.permission_context,
        )

        # Execute via CapabilityExecutor
        response = await asyncio.get_event_loop().run_in_executor(
            None, self._capability_executor.execute, execution_request, context.task_id
        )

        return response.backend_response

    async def _execute_provider(
        self,
        strategy: ExecutionStrategy,
        inputs: MappingProxyType[str, Any],
        context: BackendExecutionContext,
        capability_resolution,
    ) -> MappingProxyType[str, Any]:
        """Execute a PROVIDER capability via Planner."""
        # Build Goal from inputs
        def provider_request_builder(res, model):
            from parika.core.autonomous.provider_factories import build_provider_request
            return build_provider_request(
                capability_id=strategy.capability_id,
                inputs=inputs,
                metadata=context.permission_context,
                resolution=res,
                model=model,
            )

        goal = Goal(
            id=context.task_id,
            capability_id=strategy.capability_id,
            inputs=inputs,
            depends_on=tuple(),
            provider_request_builder=provider_request_builder,
            metadata=context.permission_context,
        )

        # Call Planner.plan() to get ExecutionPlan
        plan = self._planner.plan([goal])

        if not plan.steps:
            raise ValueError(f"Planner produced empty plan for capability '{strategy.capability_id}'")

        execution_request = plan.steps[0].execution_request

        # Execute via CapabilityExecutor
        response = await asyncio.get_event_loop().run_in_executor(
            None, self._capability_executor.execute, execution_request, context.task_id
        )

        return response.backend_response

    def is_available(self) -> bool:
        """Native backend is always available if PARIKA is running."""
        return True

    async def health_check(self) -> bool:
        """Health check - native backend is always healthy if PARIKA is running."""
        return True