"""
PARIKA Task Manager package.

Provides the TaskManager component and its primary public interfaces.
"""

from .events import (
    TaskCancelledEvent,
    TaskCompletedEvent,
    TaskCreatedEvent,
    TaskEvent,
    TaskFailedEvent,
    TaskPausedEvent,
    TaskResumedEvent,
    TaskStartedEvent,
)
from .exceptions import (
    InvalidTaskRequestError,
    TaskAlreadyCompletedError,
    TaskAlreadyRunningError,
    TaskCancelledError,
    TaskExecutionError,
    TaskManagerError,
    TaskNotFoundError,
    TaskNotRunningError,
    TaskPausedError,
)
from .request import TaskRequest
from .response import TaskResponse
from .task import Task
from .task_manager import TaskManager
from .task_status import TaskStatus

__all__ = [
    "InvalidTaskRequestError",
    "Task",
    "TaskAlreadyCompletedError",
    "TaskAlreadyRunningError",
    "TaskCancelledError",
    "TaskCancelledEvent",
    "TaskCompletedEvent",
    "TaskCreatedEvent",
    "TaskEvent",
    "TaskExecutionError",
    "TaskFailedEvent",
    "TaskManager",
    "TaskManagerError",
    "TaskNotFoundError",
    "TaskNotRunningError",
    "TaskPausedError",
    "TaskPausedEvent",
    "TaskRequest",
    "TaskResponse",
    "TaskResumedEvent",
    "TaskStartedEvent",
    "TaskStatus",
]
