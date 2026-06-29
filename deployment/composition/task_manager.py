"""Task manager runtime composition."""

from __future__ import annotations

import os

from broker_service import BrokerSettings
from redis_status_node import RedisStatusSettings, RedisTaskStatusStore
from task_manager_service import TaskManagerServerContext, TaskManagerSettings
from task_manager_service.app import create_app as create_task_manager_app


def create_task_manager_context(
    *,
    broker_settings: BrokerSettings | None = None,
    task_manager_settings: TaskManagerSettings | None = None,
    redis_settings: RedisStatusSettings | None = None,
) -> TaskManagerServerContext:
    task_manager_settings = task_manager_settings or TaskManagerSettings.from_values(dict(os.environ))
    redis_settings = redis_settings or RedisStatusSettings(
        url=task_manager_settings.redis_status_url,
        key_prefix=task_manager_settings.redis_key_prefix,
        completed_ttl_seconds=task_manager_settings.completed_ttl_seconds,
    )
    return create_task_manager_app(
        broker_settings=broker_settings,
        settings=task_manager_settings,
        status_store=RedisTaskStatusStore(settings=redis_settings),
    )
