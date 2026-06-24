"""Task manager import boundary tests."""

from __future__ import annotations

from pathlib import Path


FORBIDDEN_IMPORTS = (
    "redis_status_node",
    "manager_service",
    "project_service",
    "ingestion_service",
    "retrieval_service",
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
