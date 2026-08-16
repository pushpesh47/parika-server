"""
PARIKA Task Exceptions

Defines the exception hierarchy used by TaskManager.

These exceptions represent errors encountered while creating,
retrieving, validating, executing, and managing the lifecycle of
runtime Tasks.

All TaskManager-specific exceptions derive from
TaskManagerError.
"""

from __future__ import annotations


class TaskManagerError(Exception):
    """
    Base exception for all TaskManager errors.
    """


class TaskNotFoundError(TaskManagerError):
    """
    Raised when a requested Task cannot be found.
    """


class InvalidTaskRequestError(TaskManagerError):
    """
    Raised when a TaskRequest is structurally or semantically invalid.
    """


class TaskExecutionError(TaskManagerError):
    """
    Raised when a Task cannot be executed or its execution lifecycle
    cannot proceed successfully.
    """


class TaskAlreadyRunningError(TaskExecutionError):
    """
    Raised when attempting to execute a Task that is already running.
    """


class TaskNotRunningError(TaskExecutionError):
    """
    Raised when an operation requires a running Task.
    """


class TaskPausedError(TaskExecutionError):
    """
    Raised when an operation cannot be performed because the Task is
    currently paused.
    """


class TaskCancelledError(TaskExecutionError):
    """
    Raised when an operation cannot be performed because the Task has
    been cancelled.
    """


class TaskAlreadyCompletedError(TaskExecutionError):
    """
    Raised when an operation cannot be performed because the Task has
    already completed successfully.
    """