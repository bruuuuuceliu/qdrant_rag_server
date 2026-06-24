"""Task manager task-state repository tests."""

from __future__ import annotations

import pytest

from task_manager_service import InMemoryTaskStateRepository, SQLiteTaskStateRepository


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
