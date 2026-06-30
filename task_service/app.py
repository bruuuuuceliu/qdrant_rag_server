"""Task service application factory."""

from __future__ import annotations

import os

from broker_service import BrokerSettings, create_redpanda_bus
from shared.contracts import TOPICS
from task_service.config import TaskServiceSettings
from task_service.dispatcher import TaskServiceDispatcher
from task_service.repository import SQLiteTaskStateRepository, TaskStateRepository
from task_service.server import TaskServiceServerContext


HELPER_RESULT_TOPICS = (
    TOPICS.helper_ingestion_results,
    TOPICS.helper_retrieval_results,
    TOPICS.helper_retrieval_index_results,
    TOPICS.helper_storage_results,
)


def create_app(
    *,
    broker_settings: BrokerSettings | None = None,
    settings: TaskServiceSettings | None = None,
    state_repository: TaskStateRepository | None = None,
) -> TaskServiceServerContext:
    settings = settings or TaskServiceSettings()
    broker_settings = broker_settings or BrokerSettings.from_values(dict(os.environ))
    producer_bus = create_redpanda_bus(broker_settings)
    request_bus = create_redpanda_bus(
        broker_settings,
        topic=settings.task_request_topic,
        group_id=settings.service_name,
    )
    project_plan_result_topics = _project_plan_result_topics(settings)
    project_plan_result_consumers = tuple(
        (
            topic,
            create_redpanda_bus(
                broker_settings,
                topic=topic,
                group_id=f"{settings.service_name}.project_plan.{index}",
            ),
        )
        for index, topic in enumerate(project_plan_result_topics)
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
    dispatcher = TaskServiceDispatcher(
        producer=producer_bus,
        state_repository=state_repository or SQLiteTaskStateRepository(settings.state_db_path),
        settings=settings,
    )
    return TaskServiceServerContext(
        dispatcher=dispatcher,
        request_consumer=request_bus,
        project_plan_result_consumers=project_plan_result_consumers,
        helper_result_consumers=helper_result_consumers,
        settings=settings,
    )


def _project_plan_result_topics(settings: TaskServiceSettings) -> tuple[str, ...]:
    return (settings.project_plan_result_topic,)
