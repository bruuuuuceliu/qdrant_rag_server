"""Helper service-boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER_ROOTS = (
    ROOT / "ingestion_service" / "server",
    ROOT / "retrieval_service" / "server",
    ROOT / "retrieval_service" / "indexing",
    ROOT / "storage_node",
)


FORBIDDEN_PREFIXES = (
    "manager_service",
    "project_service",
    "task_manager_service",
    "task_service",
)


def test_helpers_do_not_depend_on_orchestration_or_project_internals() -> None:
    violations: list[str] = []
    for root in HELPER_ROOTS:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for module in _imports(path):
                if module.startswith(FORBIDDEN_PREFIXES):
                    violations.append(f"{path.relative_to(ROOT)} imports {module}")

    assert violations == []


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
