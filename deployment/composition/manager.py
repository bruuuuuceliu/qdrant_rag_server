"""Manager runtime composition."""

from __future__ import annotations

import os

from broker_service import BrokerSettings, create_redpanda_bus
from configs import AppSettings
from configs.manager import (
    ManagerGuardSettings,
    ManagerSettings,
    load_manager_guard_settings,
    load_manager_settings,
)
from manager_service.server.app import ManagerAppContext
from manager_service.server.app import create_app as create_manager_app
from manager_service.server.grpc.server import ManagerGuard
from redis_status_node import RedisStatusSettings, RedisTaskStatusStore


async def create_manager_context(
    settings: AppSettings,
    *,
    broker_settings: BrokerSettings | None = None,
    manager_settings: ManagerSettings | None = None,
    guard_settings: ManagerGuardSettings | None = None,
) -> ManagerAppContext:
    manager_settings = manager_settings or load_manager_settings(dict(os.environ))
    guard_settings = guard_settings or load_manager_guard_settings(dict(os.environ))
    broker_settings = broker_settings or BrokerSettings.from_values(dict(os.environ))
    task_producer = create_redpanda_bus(broker_settings)
    task_status_store = RedisTaskStatusStore(
        settings=RedisStatusSettings(
            url=manager_settings.task_status_url,
            key_prefix=manager_settings.task_status_key_prefix,
            completed_ttl_seconds=manager_settings.task_completed_ttl_seconds,
        )
    )
    return await create_manager_app(
        settings,
        task_producer=task_producer,
        task_status_store=task_status_store,
        manager_settings=manager_settings,
        guard=ManagerGuard(
            rate_per_second=guard_settings.rate_limit_per_second,
            burst=guard_settings.rate_limit_burst,
            max_request_bytes=guard_settings.max_request_bytes,
        ),
    )
