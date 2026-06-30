"""Task manager import boundary tests."""

from __future__ import annotations

from pathlib import Path


FORBIDDEN_IMPORTS = (
    "redis_status_node",
    "manager_service",
    "project_service",
    "ingestion_service",
    "retrieval_service",
    "task_service",
)


def test_task_manager_does_not_import_service_internals() -> None:
    root = Path(__file__).resolve().parents[2] / "task_manager_service"
    violations: list[str] = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IMPORTS:
            if f"import {forbidden}" in text or f"from {forbidden}" in text:
                violations.append(f"{path.relative_to(root)} imports {forbidden}")

    assert violations == []


def test_task_manager_does_not_expose_orchestration_state_repository() -> None:
    import task_manager_service

    assert not hasattr(task_manager_service, "InMemoryTaskStateRepository")
    assert not hasattr(task_manager_service, "SQLiteTaskStateRepository")
    assert not hasattr(task_manager_service, "TaskStateRepository")


def test_task_manager_dispatcher_has_no_helper_or_project_orchestration_methods() -> None:
    from task_manager_service import TaskManagerDispatcher

    assert not hasattr(TaskManagerDispatcher, "dispatch_domain_result")
    assert not hasattr(TaskManagerDispatcher, "finalize_helper_result")
