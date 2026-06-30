"""Broker lag target parsing and probing tests."""

from __future__ import annotations

import pytest

from broker_service import (
    BrokerLagTarget,
    BrokerSettings,
    broker_lag,
    parse_broker_lag_targets,
)
from shared.contracts import TOPICS


class FakeLagAdmin:
    settings = BrokerSettings(topic_prefix="dev.")

    async def consumer_group_lag(self, group_id: str, topic: str) -> tuple[int, ...]:
        self.call = (group_id, topic)
        return (0, 4, 2)


def test_parse_broker_lag_targets_accepts_semicolon_groups() -> None:
    targets = parse_broker_lag_targets(
        "task_manager:task.intake,project.plan.results;project_service:project.plan.requests"
    )

    assert targets == (
        BrokerLagTarget(
            group_id="task_manager",
            topics=(TOPICS.task_intake, TOPICS.project_plan_results),
        ),
        BrokerLagTarget(
            group_id="project_service",
            topics=(TOPICS.project_plan_requests,),
        ),
    )


@pytest.mark.parametrize("raw", ("task_manager", ":task.intake", "task_manager:"))
def test_parse_broker_lag_targets_rejects_malformed_values(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_broker_lag_targets(raw)


@pytest.mark.asyncio
async def test_broker_lag_computes_total_lag_from_partition_offsets() -> None:
    admin = FakeLagAdmin()

    reports = await broker_lag(
        admin,
        (BrokerLagTarget(group_id="task_manager", topics=(TOPICS.task_intake,)),),
    )

    assert reports[0].to_payload() == {
        "group_id": "task_manager",
        "total_lag": 6,
        "topics": [{"topic": "dev.task.intake", "partitions": 3, "lag": 6}],
    }
    assert admin.call == ("task_manager", "dev.task.intake")
