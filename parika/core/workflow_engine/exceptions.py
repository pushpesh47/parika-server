"""
PARIKA Workflow Exceptions

Defines the exception hierarchy used by WorkflowEngine.

These exceptions represent errors encountered while registering,
retrieving, validating, and executing Workflows.

All WorkflowEngine-specific exceptions derive from
WorkflowEngineError.
"""

from __future__ import annotations


class WorkflowEngineError(Exception):
    """
    Base exception for all WorkflowEngine errors.
    """


class WorkflowAlreadyRegisteredError(WorkflowEngineError):
    """
    Raised when attempting to register a Workflow whose identifier is
    already registered.
    """


class WorkflowNotFoundError(WorkflowEngineError):
    """
    Raised when a requested Workflow cannot be found.
    """


class WorkflowValidationError(WorkflowEngineError):
    """
    Raised when a Workflow definition fails validation.
    """


class InvalidWorkflowDefinitionError(WorkflowValidationError):
    """
    Raised when a Workflow definition is structurally invalid.
    """


class WorkflowExecutionError(WorkflowEngineError):
    """
    Raised when a Workflow execution cannot be started or completed.
    """


class WorkflowAlreadyRunningError(WorkflowExecutionError):
    """
    Raised when an execution is already running.
    """


class WorkflowNotRunningError(WorkflowExecutionError):
    """
    Raised when an operation requires a running execution.
    """


class WorkflowPausedError(WorkflowExecutionError):
    """
    Raised when an operation cannot be performed because the execution
    is paused.
    """


class WorkflowCancelledError(WorkflowExecutionError):
    """
    Raised when an operation cannot be performed because the execution
    has been cancelled.
    """


class ExecutionNotFoundError(WorkflowExecutionError):
    """
    Raised when a requested Execution cannot be found.
    """