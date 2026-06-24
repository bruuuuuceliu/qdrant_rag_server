"""Independent task manager service workspace."""

from task_manager_service.config import TaskManagerHealth, TaskManagerSettings
from task_manager_service.dispatcher import (
    DispatchResult,
    FinalizeResult,
    HelperDispatchResult,
    TaskManagerDispatcher,
)
from task_manager_service.server import TaskManagerServerContext
from task_manager_service.app import create_app
from task_manager_service.repository import (
    InMemoryTaskStateRepository,
    SQLiteTaskStateRepository,
    TaskState,
    TaskStateRepository,
)

__all__ = [
    "DispatchResult",
    "FinalizeResult",
    "HelperDispatchResult",
    "InMemoryTaskStateRepository",
    "SQLiteTaskStateRepository",
    "TaskManagerDispatcher",
    "TaskManagerHealth",
    "TaskManagerServerContext",
    "TaskManagerSettings",
    "TaskState",
    "TaskStateRepository",
    "create_app",
]
