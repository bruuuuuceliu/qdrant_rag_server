"""Postgres task state repository tests.

Run against the compose ``postgres`` service by setting ``TASK_TEST_DB_URL``
(e.g. ``postgresql://rag:...@postgres:5432/rag``); skipped when unset.
"""

from __future__ import annotations

import os

import pytest

from task_service.repository import PostgresTaskStateRepository

TEST_DB_URL = os.environ.get("TASK_TEST_DB_URL") or os.environ.get("TASK_SERVICE_STATE_DB_URL")


def _dsn() -> str:
    if not TEST_DB_URL:
        pytest.skip("TASK_TEST_DB_URL is not set; skipping Postgres task tests")
    return TEST_DB_URL


@pytest.fixture
async def repo() -> PostgresTaskStateRepository:
    repository = PostgresTaskStateRepository(_dsn())
    await repository._ensure_initialized()
    async with repository._pool.connection() as conn:
        await conn.execute(
            "DROP TABLE IF EXISTS task_step_attempts, task_results, task_steps,"
            " task_executions CASCADE"
        )
    repository._initialized = False
    await repository._ensure_initialized()
    yield repository
    await repository.close()


@pytest.mark.asyncio
async def test_execution_lifecycle(repo) -> None:
    state = await repo.record_execution("t1", data_type="d", correlation_id="c", operation="op")
    assert state.task_id == "t1"
    await repo.set_expected_helpers("t1", ("h1", "h2"))
    await repo.record_helper_plan("t1", "h1", operation="plan-op", plan={"a": 1})
    state = await repo.get("t1")
    assert state.expected_helpers == {"h1", "h2"}
    assert state.helper_plans["h1"]["operation"] == "plan-op"
    assert state.helper_plans["h1"]["plan"] == {"a": 1}

    await repo.record_helper_dispatch(
        "t1", "h1", attempt=1, source_message_id="sm1",
        lease_owner="w1", lease_expires_at="2026-08-04T10:00:00Z",
    )
    await repo.record_helper_attempt(
        "t1", "h1", attempt=1, status="retrying", retryable=True,
        error="boom", next_attempt_at="2026-08-04T09:00:00Z",
    )
    state = await repo.get("t1")
    assert state.helper_attempts["h1"][0]["event"] == "dispatch"
    assert state.helper_attempts["h1"][1]["status"] == "retrying"

    state = await repo.mark_helper_result("t1", "h2", ok=True, result={"n": 1}, attempt=1)
    assert "h2" in state.completed_helpers
    assert state.helper_results["h2"] == {"n": 1}

    state = await repo.mark_final_published("t1", status="succeeded", result={"final": True})
    assert state.final_status == "succeeded" and state.final_published is True
    assert state.final_result == {"final": True}
    assert await repo.get("missing") is None


@pytest.mark.asyncio
async def test_claim_expired_lease(repo) -> None:
    await repo.record_execution("t2", data_type="d2", correlation_id="c2", operation="op2")
    await repo.set_expected_helpers("t2", ("helper-a",))
    await repo.record_helper_dispatch(
        "t2", "helper-a", attempt=1, lease_owner="w1",
        lease_expires_at="2026-08-04T10:00:00Z",
    )
    claimed = await repo.claim_due_helper_dispatches(
        now="2026-08-04T11:00:00Z",
        lease_owner="w2",
        lease_expires_at="2026-08-04T11:30:00Z",
        max_attempts=3,
        limit=25,
    )
    assert [c.helper for c in claimed] == ["helper-a"]
    assert claimed[0].reason == "expired_lease"
    # the claim row reflects the pre-claim lease (the UPDATE owner is persisted)
    assert claimed[0].lease_owner == "w1"

    again = await repo.claim_due_helper_dispatches(
        now="2026-08-04T11:00:00Z",
        lease_owner="w3",
        lease_expires_at="2026-08-04T11:30:00Z",
        max_attempts=3,
        limit=25,
    )
    assert again == ()


@pytest.mark.asyncio
async def test_claim_terminal_lease(repo) -> None:
    await repo.record_execution("t2", data_type="d2", correlation_id="c2", operation="op2")
    await repo.set_expected_helpers("t2", ("helper-a",))
    await repo.record_helper_dispatch(
        "t2", "helper-a", attempt=3, lease_owner="w1",
        lease_expires_at="2026-08-04T10:00:00Z",
    )
    claimed = await repo.claim_due_helper_dispatches(
        now="2026-08-04T11:00:00Z",
        lease_owner="w4",
        lease_expires_at="2026-08-04T11:30:00Z",
        max_attempts=3,
        limit=25,
    )
    assert claimed and claimed[0].reason == "expired_lease_terminal"


@pytest.mark.asyncio
async def test_claim_scheduled_retry(repo) -> None:
    await repo.record_execution("t3", data_type="d3", correlation_id="c3", operation="op3")
    await repo.set_expected_helpers("t3", ("h-r",))
    await repo.record_helper_attempt(
        "t3", "h-r", attempt=1, status="retrying", retryable=True,
        next_attempt_at="2026-08-04T10:00:00Z",
    )
    claimed = await repo.claim_due_helper_dispatches(
        now="2026-08-04T11:00:00Z",
        lease_owner="w5",
        lease_expires_at="2026-08-04T11:30:00Z",
        max_attempts=3,
        limit=25,
    )
    assert [c.helper for c in claimed] == ["h-r"]
    assert claimed[0].reason == "scheduled_retry"


@pytest.mark.asyncio
async def test_claim_rejects_bad_max_attempts(repo) -> None:
    with pytest.raises(ValueError):
        await repo.claim_due_helper_dispatches(
            now="n", lease_owner="w", lease_expires_at="e", max_attempts=0
        )


@pytest.mark.asyncio
async def test_add_expected_helpers_and_retry_history(repo) -> None:
    await repo.record_execution("t4", data_type="d4", correlation_id="c4", operation="op4")
    await repo.set_expected_helpers("t4", ("h1", "h2"))
    await repo.add_expected_helpers("t4", ("h2", "h3"))
    state = await repo.get("t4")
    assert state.expected_helpers == {"h1", "h2", "h3"}

    await repo.record_helper_dispatch("t4", "h3", attempt=1, source_message_id="cmd-1")
    await repo.record_helper_attempt(
        "t4", "h3", attempt=1, status="retrying", retryable=True,
        error="timeout", source_message_id="cmd-1", failed_message_id="res-1",
        next_attempt_at="2026-08-04T10:00:00Z",
    )
    await repo.record_helper_dispatch("t4", "h3", attempt=2, source_message_id="cmd-2")
    state = await repo.get("t4")
    assert [a["status"] for a in state.helper_attempts["h3"]] == [
        "dispatched",
        "retrying",
        "dispatched",
    ]
