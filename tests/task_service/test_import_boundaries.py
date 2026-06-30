"""Task service import boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PREFIXES = (
    "manager_service",
    "task_manager_service",
    "project_service",
    "ingestion_service",
    "retrieval_service",
    "storage_node",
    "redis_status_node",
)


def test_task_service_does_not_import_service_internals() -> None:
    assert _violations(ROOT / "task_service") == []


def test_task_service_is_allowed_to_coordinate_helper_topics() -> None:
    text = (ROOT / "task_service" / "dispatcher.py").read_text(encoding="utf-8")

    assert "helper_ingestion_commands" in text
    assert "helper_retrieval_commands" in text
    assert "helper_storage_commands" in text


def _violations(root: Path) -> list[str]:
    violations: list[str] = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for module in _imports(path):
            if module.startswith(FORBIDDEN_PREFIXES):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")
    return violations


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
