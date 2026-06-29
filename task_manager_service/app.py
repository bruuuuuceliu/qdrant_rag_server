"""Task manager application factory."""

from __future__ import annotations

import os

from broker_service import BrokerSettings, create_redpanda_bus
from shared.contracts import TOPICS
from shared.contracts import TaskStatusStore
from task_manager_service.config import TaskManagerSettings
from task_manager_service.dispatcher import TaskManagerDispatcher
from task_manager_service.repository import SQLiteTaskStateRepository, TaskStateRepository
from task_manager_service.server import TaskManagerServerContext


DOMAIN_RESULT_TOPICS = (
    TOPICS.domain_project_results,
    TOPICS.domain_workflow_log_results,
    TOPICS.domain_memory_results,
    TOPICS.domain_other_results,
)

HELPER_RESULT_TOPICS = (
    TOPICS.helper_ingestion_results,
    TOPICS.helper_retrieval_results,
    TOPICS.helper_retrieval_index_results,
    TOPICS.helper_storage_results,
)


def create_app(
    *,
    broker_settings: BrokerSettings | None = None,
    settings: TaskManagerSettings | None = None,
    status_store: TaskStatusStore,
    state_repository: TaskStateRepository | None = None,
) -> TaskManagerServerContext:
    settings = settings or TaskManagerSettings()
    broker_settings = broker_settings or BrokerSettings.from_values(dict(os.environ))
    producer_bus = create_redpanda_bus(broker_settings)
    intake_bus = create_redpanda_bus(
        broker_settings,
        topic=settings.task_intake_topic,
        group_id=settings.service_name,
    )
    domain_result_consumers = tuple(
        (
            topic,
            create_redpanda_bus(
                broker_settings,
                topic=topic,
                group_id=f"{settings.service_name}.domain.{index}",
            ),
        )
        for index, topic in enumerate(DOMAIN_RESULT_TOPICS)
    )
    helper_result_consumers = tuple(
        (
            topic,
            create_redpanda_bus(
                broker_settings,
                topic=topic,
                group_id=f"{settings.service_name}.helper.{index}",
            ),
        )
        for index, topic in enumerate(HELPER_RESULT_TOPICS)
    )
    dispatcher = TaskManagerDispatcher(
        producer=producer_bus,
        status_store=status_store,
        state_repository=state_repository or SQLiteTaskStateRepository(settings.state_db_path),
        settings=settings,
    )
    return TaskManagerServerContext(
        dispatcher=dispatcher,
        intake_consumer=intake_bus,
        domain_result_consumers=domain_result_consumers,
        helper_result_consumers=helper_result_consumers,
        settings=settings,
    )
