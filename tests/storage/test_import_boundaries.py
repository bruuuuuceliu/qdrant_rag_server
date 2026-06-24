"""Storage node import boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PREFIXES = (
    "manager_service",
    "project_service",
    "workflow_log_service",
    "ingestion_service",
    "retrieval_service",
    "task_manager_service",
    "sqlite_node",
    "redis_status_node",
)


def test_storage_node_does_not_import_service_internals() -> None:
    assert _violations(ROOT / "storage_node") == []


def _violations(root: Path) -> list[str]:
    violations: list[str] = []
    for path in root.rglob("*.py"):
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
