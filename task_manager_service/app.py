"""Task manager application factory."""

from __future__ import annotations

import os

from broker_service import BrokerSettings, create_redpanda_bus
from shared.contracts import TaskStatusStore
from task_manager_service.config import TaskManagerSettings
from task_manager_service.dispatcher import TaskManagerDispatcher
from task_manager_service.server import TaskManagerServerContext


def create_app(
    *,
    broker_settings: BrokerSettings | None = None,
    settings: TaskManagerSettings | None = None,
    status_store: TaskStatusStore,
) -> TaskManagerServerContext:
    settings = settings or TaskManagerSettings()
    broker_settings = broker_settings or BrokerSettings.from_values(dict(os.environ))
    producer_bus = create_redpanda_bus(broker_settings)
    intake_bus = create_redpanda_bus(
        broker_settings,
        topic=settings.task_intake_topic,
        group_id=settings.service_name,
    )
    task_event_bus = create_redpanda_bus(
        broker_settings,
        topic=settings.task_event_topic,
        group_id=f"{settings.service_name}.events",
    )
    task_result_bus = create_redpanda_bus(
        broker_settings,
        topic=settings.task_result_topic,
        group_id=f"{settings.service_name}.results",
    )
    dispatcher = TaskManagerDispatcher(
        producer=producer_bus,
        status_store=status_store,
        settings=settings,
    )
    return TaskManagerServerContext(
        dispatcher=dispatcher,
        intake_consumer=intake_bus,
        task_event_consumer=task_event_bus,
        task_result_consumer=task_result_bus,
        settings=settings,
    )
