"""Task service runtime composition."""

from __future__ import annotations

import os

from broker_service import BrokerSettings
from task_service import TaskServiceServerContext, TaskServiceSettings
from task_service.app import create_app as create_task_service_app


def create_task_service_context(
    *,
    broker_settings: BrokerSettings | None = None,
    task_service_settings: TaskServiceSettings | None = None,
) -> TaskServiceServerContext:
    task_service_settings = task_service_settings or TaskServiceSettings.from_values(dict(os.environ))
    return create_task_service_app(
        broker_settings=broker_settings,
        settings=task_service_settings,
    )
