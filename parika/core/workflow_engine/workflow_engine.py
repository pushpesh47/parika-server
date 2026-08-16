"""
PARIKA Workflow Engine

Provides the core workflow orchestration component responsible for
managing Workflow definitions and their runtime Execution instances.

WorkflowEngine maintains the authoritative runtime registries of
Workflows and Executions, validates Workflow definitions, coordinates
workflow execution, tracks execution lifecycle, publishes workflow
events through EventBus, and performs diagnostic logging.

WorkflowEngine does not execute Capabilities directly. Capability
execution is delegated to the appropriate components.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from parika.core.event_bus import EventBus
from parika.core.logger import Logger

from .events import (
    WorkflowCompletedEvent,
    WorkflowFailedEvent,
    WorkflowCancelledEvent,
    WorkflowRegisteredEvent,
    WorkflowResumedEvent,
    WorkflowPausedEvent,
    WorkflowStartedEvent,
    WorkflowUnregisteredEvent,
)
from .exceptions import (
    InvalidWorkflowDefinitionError,
    WorkflowAlreadyRegisteredError,
    WorkflowCancelledError,
    WorkflowNotFoundError,
    WorkflowNotRunningError,
    WorkflowPausedError,
    ExecutionNotFoundError
)
from .workflow import Workflow
from .workflow_execution import Execution
from .execution_status import ExecutionStatus


class WorkflowEngine:
    """
    Coordinates Workflow registration and runtime execution.

    WorkflowEngine owns the runtime registries of Workflow definitions
    and active Execution instances. It validates Workflow definitions,
    coordinates execution lifecycle, publishes events, and delegates
    capability execution to the appropriate components.
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize the WorkflowEngine.

        Parameters
        ----------
        event_bus:
            EventBus used for publishing workflow lifecycle events.

        logger:
            Logger used for diagnostic logging.
        """
        self._event_bus = event_bus
        self._logger = logger.get_logger(__name__)

        self._workflows: dict[str, Workflow] = {}
        self._executions: dict[str, Execution] = {}

    # ------------------------------------------------------------------
    # Workflow Registry
    # ------------------------------------------------------------------

    def register(self, workflow: Workflow) -> None:
        """
        Register a Workflow.

        Parameters
        ----------
        workflow:
            Workflow definition to register.

        Raises
        ------
        WorkflowAlreadyRegisteredError
            If the Workflow is already registered.

        WorkflowValidationError
            If the Workflow definition is invalid.
        """
        if workflow.id in self._workflows:
            raise WorkflowAlreadyRegisteredError(
                f"Workflow '{workflow.id}' is already registered."
            )

        self._validate_workflow(workflow)

        self._workflows[workflow.id] = workflow

        self._event_bus.publish(
            "workflow.registered",
            WorkflowRegisteredEvent(workflow_id=workflow.id)
        )

        self._logger.info(
            "Registered workflow '%s'.",
            workflow.id,
        )

    def unregister(self, workflow_id: str) -> None:
        """
        Unregister a Workflow.

        Parameters
        ----------
        workflow_id:
            Identifier of the Workflow.

        Raises
        ------
        WorkflowNotFoundError
            If the Workflow is not registered.
        """
        workflow = self._workflows.pop(workflow_id, None)

        if workflow is None:
            raise WorkflowNotFoundError(
                f"Workflow '{workflow_id}' is not registered."
            )

        self._event_bus.publish(
            "workflow.unregistered",
            WorkflowUnregisteredEvent(workflow_id=workflow_id)
        )

        self._logger.info(
            "Unregistered workflow '%s'.",
            workflow_id,
        )

    def get(self, workflow_id: str) -> Workflow:
        """
        Retrieve a registered Workflow.
        """
        try:
            return self._workflows[workflow_id]
        except KeyError as exc:
            raise WorkflowNotFoundError(
                f"Workflow '{workflow_id}' is not registered."
            ) from exc

    def contains(self, workflow_id: str) -> bool:
        """
        Determine whether a Workflow is registered.
        """
        return workflow_id in self._workflows

    def get_all(self) -> Mapping[str, Workflow]:
        """
        Return all registered Workflows.
        """
        return MappingProxyType(self._workflows)

    def count(self) -> int:
        """
        Return the number of registered Workflows.
        """
        return len(self._workflows)

    # ------------------------------------------------------------------
    # Execution Registry
    # ------------------------------------------------------------------

    def execute(
        self,
        workflow_id: str,
        *,
        context_id: str | None = None,
    ) -> Execution:
        """
        Execute a registered Workflow.

        Parameters
        ----------
        workflow_id:
            Identifier of the Workflow.

        context_id:
            Optional existing Context identifier.

        Returns
        -------
        Execution
            Newly created Execution.

        Raises
        ------
        WorkflowNotFoundError
            If the Workflow is not registered.
        """
        workflow = self.get(workflow_id)

        execution = self._create_execution(
            workflow,
            context_id=context_id,
        )

        self._executions[execution.id] = execution

        self._event_bus.publish(
            "workflow.started",
            WorkflowStartedEvent(
                workflow_id=workflow.id,
                execution_id=execution.id,
            )
        )

        self._logger.info(
            "Started workflow '%s' (execution='%s').",
            workflow.id,
            execution.id,
        )

        self._execute(execution)

        return execution

    def pause(self, execution_id: str) -> None:
        """
        Pause a running Execution.
        """
        execution = self.get_active_execution(execution_id)

        if execution.status is ExecutionStatus.PAUSED:
            raise WorkflowPausedError(
                f"Execution '{execution_id}' is already paused."
            )

        if execution.status is not ExecutionStatus.RUNNING:
            raise WorkflowNotRunningError(
                f"Execution '{execution_id}' is not running."
            )

        execution.status = ExecutionStatus.PAUSED

        self._event_bus.publish(
            "workflow.paused",
            WorkflowPausedEvent(
                workflow_id=execution.workflow_id,
                execution_id=execution.id,
            )
        )

        self._logger.info(
            "Paused execution '%s'.",
            execution.id,
        )

    def resume(self, execution_id: str) -> None:
        """
        Resume a paused Execution.
        """
        execution = self.get_active_execution(execution_id)

        if execution.status is not ExecutionStatus.PAUSED:
            raise WorkflowPausedError(
                f"Execution '{execution_id}' is not paused."
            )

        execution.status = ExecutionStatus.RUNNING

        self._event_bus.publish(
            "workflow.resumed",
            WorkflowResumedEvent(
                workflow_id=execution.workflow_id,
                execution_id=execution.id,
            )
        )

        self._logger.info(
            "Resumed execution '%s'.",
            execution.id,
        )

        self._execute(execution)

    def cancel(self, execution_id: str) -> None:
        """
        Cancel an Execution.
        """
        execution = self.get_active_execution(execution_id)

        if execution.status is ExecutionStatus.CANCELLED:
            raise WorkflowCancelledError(
                f"Execution '{execution_id}' is already cancelled."
            )

        execution.status = ExecutionStatus.CANCELLED

        self._event_bus.publish(
            "workflow.cancelled",
            WorkflowCancelledEvent(
                workflow_id=execution.workflow_id,
                execution_id=execution.id,
            )
        )

        self._logger.info(
            "Cancelled execution '%s'.",
            execution.id,
        )

        self._cleanup_execution(execution)

    def get_active_execution(
        self,
        execution_id: str,
    ) -> Execution:
        """
        Retrieve an active Execution.
        """
        try:
            return self._executions[execution_id]
        except KeyError as exc:
            raise ExecutionNotFoundError(
                f"Execution '{execution_id}' is not active."
            ) from exc

    def get_active_executions(self) -> Mapping[str, Execution]:
        """
        Return all active Executions.

        Returns
        -------
        Mapping[str, Execution]
            Read-only mapping of Execution identifiers to active Execution
            instances.
        """
        return MappingProxyType(self._executions)

    def contains_active_execution(
        self,
        execution_id: str,
    ) -> bool:
        """
        Determine whether an Execution is currently active.
        """
        return execution_id in self._executions

    def active_execution_count(self) -> int:
        """
        Return the number of active Executions.
        """
        return len(self._executions)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _validate_workflow(self, workflow: Workflow) -> None:
        """
        Validate a Workflow definition.

        Raises
        ------
        InvalidWorkflowDefinitionError
            If the Workflow definition is invalid.
        """
        if not workflow.step_definitions:
            raise InvalidWorkflowDefinitionError(
                "Workflow must contain at least one Step."
            )

        if workflow.entry_step_id not in workflow.step_definitions:
            raise InvalidWorkflowDefinitionError(
                f"Entry Step '{workflow.entry_step_id}' does not exist."
            )

        for step in workflow.step_definitions.values():
            for next_step_id in step.next_step_ids:
                if next_step_id not in workflow.step_definitions:
                    raise InvalidWorkflowDefinitionError(
                        f"Unknown Step '{next_step_id}'."
                    )

    def _create_execution(
        self,
        workflow: Workflow,
        *,
        context_id: str | None,
    ) -> Execution:
        """
        Create a new Execution.
        """
        raise NotImplementedError

    def _execute(self, execution: Execution) -> None:
        """
        Coordinate workflow execution.
        """
        while execution.status is ExecutionStatus.RUNNING:
            self._execute_step(execution)

    def _execute_step(self, execution: Execution) -> None:
        """
        Execute the current Step.
        """
        raise NotImplementedError

    def _advance_execution(
        self,
        execution: Execution,
        next_step_id: str | None,
    ) -> None:
        """
        Advance an Execution to its next Step.
        """
        if next_step_id is None:
            self._complete_execution(execution)
            return

        execution.current_step_id = next_step_id

    def _complete_execution(
        self,
        execution: Execution,
    ) -> None:
        """
        Complete an Execution successfully.
        """
        execution.status = ExecutionStatus.COMPLETED

        self._event_bus.publish(
            "workflow.completed",
            WorkflowCompletedEvent(
                workflow_id=execution.workflow_id,
                execution_id=execution.id,
            )
        )

        self._logger.info(
            "Completed execution '%s'.",
            execution.id,
        )

        self._cleanup_execution(execution)

    def _fail_execution(
        self,
        execution: Execution,
        reason: str,
    ) -> None:
        """
        Fail an Execution.
        """
        execution.status = ExecutionStatus.FAILED
        execution.failure_reason = reason

        self._event_bus.publish(
            "workflow.failed",
            WorkflowFailedEvent(
                workflow_id=execution.workflow_id,
                execution_id=execution.id,
                failure_reason=reason,
            )
        )

        self._logger.error(
            "Execution '%s' failed: %s",
            execution.id,
            reason,
        )

        self._cleanup_execution(execution)

    def _cleanup_execution(
        self,
        execution: Execution,
    ) -> None:
        """
        Remove an Execution from the active registry.
        """
        self._executions.pop(execution.id, None)
        self._logger.debug(
            "Cleaned up execution '%s'.",
            execution.id,
        )