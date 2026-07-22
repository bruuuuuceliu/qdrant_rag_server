"""Task service execution-state repository tests."""

from __future__ import annotations

import json
import sqlite3

import pytest

from task_service import InMemoryTaskStateRepository, SQLiteTaskStateRepository


@pytest.mark.asyncio
async def test_task_state_repository_tracks_expected_and_completed_helpers() -> None:
    repository = InMemoryTaskStateRepository()

    await repository.set_expected_helpers("task-1", ("a",))
    await repository.add_expected_helpers("task-1", ("b",))
    state = await repository.mark_helper_result("task-1", "a", ok=True, result={"ok": True})

    assert state.complete is False
    assert state.expected_helpers == {"a", "b"}
    assert state.failed is False
    assert state.helper_results == {"a": {"ok": True}}

    state = await repository.mark_helper_result("task-1", "b", ok=True, result={"ok": True, "value": 2})

    assert state.complete is True
    assert state.failed is False
    assert state.helper_results["b"] == {"ok": True, "value": 2}


@pytest.mark.asyncio
async def test_task_state_repository_tracks_failed_helpers() -> None:
    repository = InMemoryTaskStateRepository()

    await repository.set_expected_helpers("task-1", ("a",))
    state = await repository.mark_helper_result("task-1", "a", ok=False, result={"ok": False})

    assert state.complete is True
    assert state.failed is True


@pytest.mark.asyncio
async def test_sqlite_task_state_repository_persists_fan_in_state(tmp_path) -> None:
    db_path = tmp_path / "task_state.db"
    repository = SQLiteTaskStateRepository(db_path)

    await repository.set_expected_helpers("task-1", ("a",))
    await repository.add_expected_helpers("task-1", ("b",))
    await repository.mark_helper_result("task-1", "a", ok=True, result={"ok": True})

    reopened = SQLiteTaskStateRepository(db_path)
    state = await reopened.get("task-1")

    assert state is not None
    assert state.complete is False
    assert state.expected_helpers == {"a", "b"}
    assert state.completed_helpers == {"a"}
    assert state.helper_results == {"a": {"ok": True}}

    state = await reopened.mark_helper_result("task-1", "b", ok=False, result={"ok": False})

    assert state.complete is True
    assert state.failed is True


@pytest.mark.asyncio
async def test_sqlite_task_state_repository_persists_final_publication(tmp_path) -> None:
    db_path = tmp_path / "task_state.db"
    repository = SQLiteTaskStateRepository(db_path)

    await repository.mark_final_published(
        "task-1",
        status="completed",
        result={"ok": True},
    )

    reopened = SQLiteTaskStateRepository(db_path)
    state = await reopened.get("task-1")

    assert state is not None
    assert state.final_published is True
    assert state.final_status == "completed"
    assert state.final_result == {"ok": True}


@pytest.mark.asyncio
async def test_sqlite_task_state_repository_persists_helper_plans(tmp_path) -> None:
    db_path = tmp_path / "task_state.db"
    repository = SQLiteTaskStateRepository(db_path)

    await repository.record_helper_plan(
        "task-1",
        "helper.topic",
        operation="search",
        plan={"project_id": "p1"},
    )

    reopened = SQLiteTaskStateRepository(db_path)
    state = await reopened.get("task-1")

    assert state is not None
    assert state.expected_helpers == {"helper.topic"}
    assert state.helper_plans == {
        "helper.topic": {
            "operation": "search",
            "plan": {"project_id": "p1"},
        }
    }


@pytest.mark.asyncio
async def test_sqlite_task_state_repository_persists_execution_metadata(tmp_path) -> None:
    db_path = tmp_path / "task_state.db"
    repository = SQLiteTaskStateRepository(db_path)

    await repository.record_execution(
        "task-1",
        data_type="project_document",
        correlation_id="corr-1",
        operation="search",
    )
    await repository.record_execution("task-1", operation="delete")

    state = await repository.get("task-1")
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT data_type, correlation_id, operation
              FROM task_executions
             WHERE task_id = ?
            """,
            ("task-1",),
        ).fetchone()

    assert state is not None
    assert state.data_type == "project_document"
    assert state.correlation_id == "corr-1"
    assert state.operation == "delete"
    assert row == ("project_document", "corr-1", "delete")


@pytest.mark.asyncio
async def test_sqlite_task_state_repository_claims_due_scheduled_retries(tmp_path) -> None:
    db_path = tmp_path / "task_state.db"
    repository = SQLiteTaskStateRepository(db_path)

    await repository.record_execution(
        "task-1",
        data_type="project_document",
        correlation_id="corr-1",
        operation="search",
    )
    await repository.record_helper_plan(
        "task-1",
        "helper.topic",
        operation="search",
        plan={"project_id": "p1"},
    )
    await repository.record_helper_attempt(
        "task-1",
        "helper.topic",
        attempt=1,
        status="retrying",
        retryable=True,
        error="timeout",
        source_message_id="cmd-1",
        failed_message_id="result-1",
        next_attempt_at="2026-07-22T00:00:05Z",
    )

    due = await repository.claim_due_helper_dispatches(
        now="2026-07-22T00:00:06Z",
        lease_owner="task-service-1",
        lease_expires_at="2026-07-22T00:01:00Z",
        max_attempts=3,
        limit=10,
    )
    second = await repository.claim_due_helper_dispatches(
        now="2026-07-22T00:00:07Z",
        lease_owner="task-service-2",
        lease_expires_at="2026-07-22T00:01:00Z",
        max_attempts=3,
        limit=10,
    )

    assert len(due) == 1
    assert due[0].reason == "scheduled_retry"
    assert due[0].attempt == 1
    assert due[0].data_type == "project_document"
    assert due[0].correlation_id == "corr-1"
    assert due[0].operation == "search"
    assert due[0].plan == {"project_id": "p1"}
    assert second == ()


@pytest.mark.asyncio
async def test_sqlite_task_state_repository_claims_expired_helper_leases(tmp_path) -> None:
    db_path = tmp_path / "task_state.db"
    repository = SQLiteTaskStateRepository(db_path)

    await repository.record_execution(
        "task-1",
        data_type="project_document",
        correlation_id="corr-1",
        operation="search",
    )
    await repository.record_helper_plan(
        "task-1",
        "helper.topic",
        operation="search",
        plan={"project_id": "p1"},
    )
    await repository.record_helper_dispatch(
        "task-1",
        "helper.topic",
        attempt=1,
        source_message_id="cmd-1",
        lease_owner="task-service-1",
        lease_expires_at="2026-07-22T00:00:05Z",
    )

    due = await repository.claim_due_helper_dispatches(
        now="2026-07-22T00:00:06Z",
        lease_owner="task-service-2",
        lease_expires_at="2026-07-22T00:01:00Z",
        max_attempts=3,
        limit=10,
    )

    assert len(due) == 1
    assert due[0].reason == "expired_lease"
    assert due[0].attempt == 1
    assert due[0].last_source_message_id == "cmd-1"


@pytest.mark.asyncio
async def test_sqlite_task_state_repository_uses_explicit_execution_step_result_tables(
    tmp_path,
) -> None:
    db_path = tmp_path / "task_state.db"
    repository = SQLiteTaskStateRepository(db_path)

    await repository.record_helper_plan(
        "task-1",
        "helper.topic",
        operation="search",
        plan={"project_id": "p1"},
    )
    await repository.record_helper_dispatch(
        "task-1",
        "helper.topic",
        attempt=1,
        source_message_id="cmd-1",
        lease_owner="task-service-1",
        lease_expires_at="2026-07-22T00:01:00Z",
    )
    await repository.mark_helper_result(
        "task-1",
        "helper.topic",
        ok=True,
        result={"ok": True},
        source_message_id="cmd-1",
        failed_message_id="result-1",
    )
    await repository.mark_final_published("task-1", status="completed", result={"ok": True})

    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        step = conn.execute(
            """
            SELECT
                expected,
                completed,
                failed,
                operation,
                plan_json,
                result_json,
                attempt,
                last_status,
                lease_owner,
                lease_expires_at,
                last_source_message_id
              FROM task_steps
             WHERE task_id = ? AND helper = ?
            """,
            ("task-1", "helper.topic"),
        ).fetchone()
        attempts = conn.execute(
            """
            SELECT event, status, attempt, source_message_id
              FROM task_step_attempts
             WHERE task_id = ? AND helper = ?
             ORDER BY id
            """,
            ("task-1", "helper.topic"),
        ).fetchall()
        result = conn.execute(
            """
            SELECT final_status, result_json, published
              FROM task_results
             WHERE task_id = ?
            """,
            ("task-1",),
        ).fetchone()

    assert {"task_executions", "task_steps", "task_step_attempts", "task_results"} <= tables
    assert step == (
        1,
        1,
        0,
        "search",
        json.dumps({"project_id": "p1"}, sort_keys=True),
        json.dumps({"ok": True}, sort_keys=True),
        1,
        "completed",
        "task-service-1",
        "2026-07-22T00:01:00Z",
        "cmd-1",
    )
    assert attempts == [
        ("dispatch", "dispatched", 1, "cmd-1"),
        ("result", "completed", 1, "cmd-1"),
    ]
    assert result == ("completed", json.dumps({"ok": True}, sort_keys=True), 1)


@pytest.mark.asyncio
async def test_sqlite_task_state_repository_records_retry_attempt_history(tmp_path) -> None:
    db_path = tmp_path / "task_state.db"
    repository = SQLiteTaskStateRepository(db_path)

    await repository.record_helper_plan(
        "task-1",
        "helper.topic",
        operation="search",
        plan={"project_id": "p1"},
    )
    await repository.record_helper_dispatch(
        "task-1",
        "helper.topic",
        attempt=1,
        source_message_id="cmd-1",
    )
    await repository.record_helper_attempt(
        "task-1",
        "helper.topic",
        attempt=1,
        status="retrying",
        retryable=True,
        error="timeout",
        source_message_id="cmd-1",
        failed_message_id="result-1",
        next_attempt_at="2026-07-22T00:00:05Z",
    )
    await repository.record_helper_dispatch(
        "task-1",
        "helper.topic",
        attempt=2,
        source_message_id="cmd-2",
    )

    state = await repository.get("task-1")
    with sqlite3.connect(db_path) as conn:
        step = conn.execute(
            """
            SELECT attempt, last_status, retryable, next_attempt_at, last_error, last_source_message_id
              FROM task_steps
             WHERE task_id = ? AND helper = ?
            """,
            ("task-1", "helper.topic"),
        ).fetchone()

    assert state is not None
    assert [item["status"] for item in state.helper_attempts["helper.topic"]] == [
        "dispatched",
        "retrying",
        "dispatched",
    ]
    assert step == (2, "dispatched", 0, None, "timeout", "cmd-2")


@pytest.mark.asyncio
async def test_sqlite_task_state_repository_migrates_legacy_task_states_table(tmp_path) -> None:
    db_path = tmp_path / "task_state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE task_states (
                task_id TEXT PRIMARY KEY,
                expected_helpers TEXT NOT NULL,
                completed_helpers TEXT NOT NULL,
                failed_helpers TEXT NOT NULL,
                helper_results TEXT NOT NULL,
                helper_plans TEXT NOT NULL DEFAULT '{}',
                final_status TEXT NOT NULL DEFAULT '',
                final_result TEXT NOT NULL DEFAULT '{}',
                final_published INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO task_states (
                task_id,
                expected_helpers,
                completed_helpers,
                failed_helpers,
                helper_results,
                helper_plans,
                final_status,
                final_result,
                final_published
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-1",
                json.dumps(["helper.topic"]),
                json.dumps(["helper.topic"]),
                json.dumps([]),
                json.dumps({"helper.topic": {"ok": True}}, sort_keys=True),
                json.dumps(
                    {
                        "helper.topic": {
                            "operation": "search",
                            "plan": {"project_id": "p1"},
                        }
                    },
                    sort_keys=True,
                ),
                "completed",
                json.dumps({"ok": True}, sort_keys=True),
                1,
            ),
        )

    repository = SQLiteTaskStateRepository(db_path)
    state = await repository.get("task-1")

    assert state is not None
    assert state.expected_helpers == {"helper.topic"}
    assert state.completed_helpers == {"helper.topic"}
    assert state.helper_results == {"helper.topic": {"ok": True}}
    assert state.helper_plans == {
        "helper.topic": {
            "operation": "search",
            "plan": {"project_id": "p1"},
        }
    }
    assert state.final_status == "completed"
    assert state.final_result == {"ok": True}
    assert state.final_published is True


@pytest.mark.asyncio
async def test_sqlite_task_state_repository_migrates_unpublished_final_without_published_at(
    tmp_path,
) -> None:
    db_path = tmp_path / "task_state.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE task_states (
                task_id TEXT PRIMARY KEY,
                expected_helpers TEXT NOT NULL,
                completed_helpers TEXT NOT NULL,
                failed_helpers TEXT NOT NULL,
                helper_results TEXT NOT NULL,
                final_status TEXT NOT NULL DEFAULT '',
                final_result TEXT NOT NULL DEFAULT '{}',
                final_published INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO task_states (
                task_id,
                expected_helpers,
                completed_helpers,
                failed_helpers,
                helper_results,
                final_status,
                final_result,
                final_published
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "task-1",
                json.dumps(["helper.topic"]),
                json.dumps(["helper.topic"]),
                json.dumps([]),
                json.dumps({"helper.topic": {"ok": True}}, sort_keys=True),
                "completed",
                json.dumps({"ok": True}, sort_keys=True),
                0,
            ),
        )

    repository = SQLiteTaskStateRepository(db_path)
    state = await repository.get("task-1")
    with sqlite3.connect(db_path) as conn:
        published_at = conn.execute(
            "SELECT published_at FROM task_results WHERE task_id = ?",
            ("task-1",),
        ).fetchone()[0]

    assert state is not None
    assert state.final_status == "completed"
    assert state.final_published is False
    assert published_at is None
