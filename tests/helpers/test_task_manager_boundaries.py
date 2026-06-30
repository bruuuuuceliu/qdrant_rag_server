"""Helper/task-manager boundary tests."""

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


def test_helpers_do_not_depend_on_task_manager() -> None:
    violations: list[str] = []
    for root in HELPER_ROOTS:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for module in _imports(path):
                if module.startswith("task_manager_service"):
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
